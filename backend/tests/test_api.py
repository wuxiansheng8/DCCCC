import asyncio
import os
import tempfile
from datetime import datetime, timedelta

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "password"
os.environ["SECRET_KEY"] = "test-secret"

from fastapi.testclient import TestClient
import main
import models
import discord_manager
from database import SessionLocal

client = TestClient(main.app)


def auth_headers():
    response = client.post("/api/login", data={"username": "admin", "password": "password"})
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def fake_token_check(token_obj):
    return "standby", None


async def fake_missing_guilds_check(token_obj):
    return set(), None


def test_token_lifecycle_and_status(monkeypatch):
    headers = auth_headers()
    monkeypatch.setattr(discord_manager, "check_discord_token", fake_token_check)

    response = client.post(
        "/api/tokens",
        json={"token": "abcdefghijklmnopqrstuvwxyz123456", "note": "backup account"},
        headers=headers,
    )
    assert response.status_code == 200
    token_id = response.json()["id"]
    assert response.json()["status"] == "standby"
    assert response.json()["note"] == "backup account"

    duplicate = client.post("/api/tokens", json={"token": "abcdefghijklmnopqrstuvwxyz123456"}, headers=headers)
    assert duplicate.status_code == 409

    disabled = client.patch(f"/api/tokens/{token_id}/status", json={"status": "disabled"}, headers=headers)
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"

    renamed = client.patch(f"/api/tokens/{token_id}", json={"note": "new note"}, headers=headers)
    assert renamed.status_code == 200
    assert renamed.json()["note"] == "new note"

    extra = client.post(
        "/api/tokens",
        json={"token": "bulk-delete-abcdefghijklmnopqrstuvwxyz123456", "note": "delete me"},
        headers=headers,
    )
    bulk_deleted = client.post(
        "/api/tokens/bulk-delete",
        json={"ids": [extra.json()["id"]]},
        headers=headers,
    )
    assert bulk_deleted.status_code == 200
    assert bulk_deleted.json()["deleted_ids"] == [extra.json()["id"]]

    status = client.get("/api/system/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["token_total"] >= 1
    assert status.json()["token_disabled"] >= 1
    assert "stable_uptime_seconds" in status.json()
    assert len(status.json()["runtime_hours"]) == 24
    assert "downtime_count_24h" in status.json()
    assert "downtime_seconds_24h" in status.json()
    assert "token_switch_count_24h" in status.json()


def test_stable_uptime_seconds_when_active_token_is_online():
    headers = auth_headers()
    db = SessionLocal()
    try:
        token = models.DiscordToken(
            token="stable-uptime-abcdefghijklmnopqrstuvwxyz123456",
            note="uptime",
            status="online",
        )
        db.add(token)
        db.commit()
        db.refresh(token)
        config = db.query(models.SystemConfig).first()
        config.is_running = True
        config.active_token_id = token.id
        config.stable_uptime_started_at = datetime.utcnow() - timedelta(seconds=75)
        db.commit()
    finally:
        db.close()

    response = client.get("/api/system/status", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["stable_uptime_seconds"] >= 70
    assert body["stable_uptime_started_at"] is not None
    assert len(body["runtime_hours"]) == 24


def test_token_failover_does_not_reset_stable_uptime():
    db = SessionLocal()
    try:
        origin = models.DiscordToken(
            token="origin-failover-abcdefghijklmnopqrstuvwxyz123456",
            note="origin",
            status="online",
        )
        backup = models.DiscordToken(
            token="backup-failover-abcdefghijklmnopqrstuvwxyz123456",
            note="backup",
            status="online",
        )
        db.add(origin)
        db.add(backup)
        db.commit()
        db.refresh(origin)
        db.refresh(backup)
        started_at = datetime.utcnow() - timedelta(minutes=5)
        config = db.query(models.SystemConfig).first()
        config.is_running = True
        config.active_token_id = origin.id
        config.stable_uptime_started_at = started_at
        db.commit()
    finally:
        db.close()

    asyncio.run(discord_manager.MonitorManager().mark_token_failure(origin.id, "offline", "Discord client disconnected."))

    db = SessionLocal()
    try:
        config = db.query(models.SystemConfig).first()
        assert config.active_token_id == backup.id
        assert config.stable_uptime_started_at == started_at
        assert db.query(models.SystemLog).filter(models.SystemLog.message == f"Token switch: {origin.id} -> {backup.id}.").count() == 1
        assert db.query(models.SystemLog).filter(models.SystemLog.message.like("Service unavailable:%")).count() == 0
    finally:
        db.close()


def test_service_unavailable_sends_alert(monkeypatch):
    sent_alerts = []

    async def fake_service_alert(title, body, level="info"):
        sent_alerts.append((title, body, level))

    monkeypatch.setattr(discord_manager, "send_service_alert", fake_service_alert)

    db = SessionLocal()
    try:
        origin = models.DiscordToken(
            token="unavailable-alert-abcdefghijklmnopqrstuvwxyz123456",
            note="origin",
            status="online",
        )
        db.add(origin)
        db.commit()
        db.refresh(origin)
        config = db.query(models.SystemConfig).first()
        config.is_running = True
        config.active_token_id = origin.id
        config.stable_uptime_started_at = datetime.utcnow() - timedelta(minutes=5)
        db.commit()
    finally:
        db.close()

    asyncio.run(discord_manager.MonitorManager().mark_token_failure(origin.id, "offline", "Discord client disconnected."))

    assert sent_alerts == [("服务不可用", "监控服务已断开：Discord client disconnected.", "error")]


def test_target_validation():
    headers = auth_headers()

    response = client.post("/api/targets/servers", json={"guild_id": "abc", "name": "bad"}, headers=headers)
    assert response.status_code == 422

    response = client.post("/api/targets/users", json={"username": "bad user"}, headers=headers)
    assert response.status_code == 422

    response = client.post("/api/targets/users", json={"username": "targetuser"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["username"] == "targetuser"
    assert response.json()["user_id"] is None

    duplicate = client.post("/api/targets/users", json={"username": "targetuser"}, headers=headers)
    assert duplicate.status_code == 409


def test_bulk_delete_targets():
    headers = auth_headers()

    server = client.post(
        "/api/targets/servers",
        json={"guild_id": "223456789012345678", "name": "bulk server"},
        headers=headers,
    )
    user = client.post(
        "/api/targets/users",
        json={"username": "bulkuser", "note": "bulk user"},
        headers=headers,
    )
    channel = client.post(
        "/api/targets/channels",
        json={"channel_id": "323456789012345678", "note": "bulk channel"},
        headers=headers,
    )

    assert server.status_code == 200
    assert user.status_code == 200
    assert channel.status_code == 200

    deleted_servers = client.post("/api/targets/servers/bulk-delete", json={"ids": [server.json()["id"]]}, headers=headers)
    deleted_users = client.post("/api/targets/users/bulk-delete", json={"ids": [user.json()["id"]]}, headers=headers)
    deleted_channels = client.post("/api/targets/channels/bulk-delete", json={"ids": [channel.json()["id"]]}, headers=headers)

    assert deleted_servers.status_code == 200
    assert deleted_users.status_code == 200
    assert deleted_channels.status_code == 200
    assert deleted_servers.json()["deleted_ids"] == [server.json()["id"]]
    assert deleted_users.json()["deleted_ids"] == [user.json()["id"]]
    assert deleted_channels.json()["deleted_ids"] == [channel.json()["id"]]


def test_log_retention_keeps_only_one_day():
    headers = auth_headers()
    db = SessionLocal()
    try:
        db.add(models.SystemLog(level="info", message="old", created_at=datetime.utcnow() - timedelta(hours=25)))
        db.add(models.SystemLog(level="info", message="same day", created_at=datetime.utcnow() - timedelta(hours=2)))
        db.add(models.SystemLog(level="info", message="fresh", created_at=datetime.utcnow()))
        db.commit()
    finally:
        db.close()

    response = client.get("/api/logs", headers=headers)
    assert response.status_code == 200
    messages = [item["message"] for item in response.json()]
    assert "fresh" in messages
    assert "same day" in messages
    assert "old" not in messages


def test_telegram_test_endpoint(monkeypatch):
    headers = auth_headers()

    async def fake_send(bot_token, chat_id, message_text, retries=2):
        return True, None

    monkeypatch.setattr(main, "send_telegram_message", fake_send)
    response = client.post(
        "/api/config/test-telegram",
        json={"tg_bot_token": "123456:ABC", "tg_chat_id": "123456"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["detail"] == "Telegram test message sent successfully"


def test_ai_config_update_and_clear_key():
    headers = auth_headers()

    response = client.put(
        "/api/config",
        json={
            "tg_bot_token": "123456:ABC",
            "tg_chat_id": "123456",
            "ai_enabled": True,
            "ai_api_key": "sk-test",
            "ai_base_url": "https://api.deepseek.com",
            "ai_model": "deepseek-chat",
            "ai_backup_api_key": "sk-backup",
            "ai_backup_base_url": "https://backup.example.com/v1",
            "ai_backup_model": "backup-chat",
            "ai_forward_format": "summary_original",
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["ai_enabled"] is True
    assert response.json()["ai_api_key"] == "sk-test"
    assert response.json()["ai_backup_api_key"] == "sk-backup"
    assert response.json()["ai_backup_base_url"] == "https://backup.example.com/v1"
    assert response.json()["ai_backup_model"] == "backup-chat"
    assert response.json()["ai_active_provider"] == "primary"
    assert response.json()["ai_forward_format"] == "summary_original"

    cleared = client.put(
        "/api/config",
        json={"ai_enabled": False, "ai_api_key": None},
        headers=headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["ai_enabled"] is False
    assert cleared.json()["ai_api_key"] is None


def test_ai_balance_endpoint(monkeypatch):
    headers = auth_headers()
    calls = []

    async def fake_balance(api_key, base_url):
        calls.append((api_key, base_url))
        return {
            "is_available": True,
            "balance_infos": [
                {
                    "currency": "CNY",
                    "total_balance": "12.34",
                    "granted_balance": "0",
                    "topped_up_balance": "12.34",
                }
            ],
        }, None

    monkeypatch.setattr(main, "get_api_balance", fake_balance)
    client.put(
        "/api/config",
        json={
            "ai_api_key": "sk-test",
            "ai_base_url": "https://api.deepseek.com",
            "ai_backup_api_key": "sk-backup",
            "ai_backup_base_url": "https://backup.example.com/v1",
            "ai_backup_model": "backup-chat",
        },
        headers=headers,
    )

    response = client.get("/api/config/ai-balance", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_available"] is True
    assert response.json()["balance_infos"][0]["currency"] == "CNY"
    assert calls[-1] == ("sk-test", "https://api.deepseek.com")

    backup_response = client.get("/api/config/ai-balance/backup", headers=headers)
    assert backup_response.status_code == 200
    assert calls[-1] == ("sk-backup", "https://backup.example.com/v1")


def test_ai_summary_test_endpoint(monkeypatch):
    headers = auth_headers()

    async def fake_summary(config, message_text):
        return "建议等 validator emissions 稳定后再启动 subnet。", None, "primary", None

    monkeypatch.setattr(main, "generate_chinese_summary_with_failover", fake_summary)
    client.put(
        "/api/config",
        json={"ai_api_key": "sk-test", "ai_base_url": "https://api.deepseek.com", "ai_model": "deepseek-chat"},
        headers=headers,
    )

    response = client.post("/api/config/test-ai", headers=headers)
    assert response.status_code == 200
    assert "validator emissions" in response.json()["summary"]


def test_ai_summary_provider_test_endpoint(monkeypatch):
    headers = auth_headers()
    calls = []

    async def fake_translation(api_key, base_url, model, message_text):
        calls.append((api_key, base_url, model, message_text))
        return "测试翻译", None, None

    monkeypatch.setattr(main, "request_chinese_translation", fake_translation)
    client.put(
        "/api/config",
        json={
            "ai_api_key": "sk-test",
            "ai_base_url": "https://api.deepseek.com",
            "ai_model": "deepseek-chat",
            "ai_backup_api_key": "sk-backup",
            "ai_backup_base_url": "https://backup.example.com/v1",
            "ai_backup_model": "backup-chat",
        },
        headers=headers,
    )

    response = client.post("/api/config/test-ai/backup", headers=headers)

    assert response.status_code == 200
    assert response.json()["summary"] == "测试翻译"
    assert calls[-1][:3] == ("sk-backup", "https://backup.example.com/v1", "backup-chat")


def test_manual_token_check(monkeypatch):
    headers = auth_headers()
    monkeypatch.setattr(discord_manager, "check_discord_token", fake_token_check)

    created = client.post(
        "/api/tokens",
        json={"token": "token-check-abcdefghijklmnopqrstuvwxyz123456", "note": "check me"},
        headers=headers,
    )
    token_id = created.json()["id"]
    response = client.post(f"/api/tokens/{token_id}/check", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "standby"
    assert response.json()["last_checked_at"] is not None
    assert response.json()["next_check_at"] is not None


def test_manual_server_coverage_check(monkeypatch):
    headers = auth_headers()
    monkeypatch.setattr(discord_manager, "check_discord_token", fake_token_check)
    monkeypatch.setattr(discord_manager, "check_discord_token_guilds", fake_missing_guilds_check)

    server = client.post(
        "/api/targets/servers",
        json={"guild_id": "123456789012345679", "name": "coverage guild"},
        headers=headers,
    )
    assert server.status_code == 200

    created = client.post(
        "/api/tokens",
        json={"token": "manual-coverage-abcdefghijklmnopqrstuvwxyz123456", "note": "coverage check"},
        headers=headers,
    )
    token_id = created.json()["id"]
    response = client.post(f"/api/tokens/{token_id}/check-servers", headers=headers)
    assert response.status_code == 200
    assert "未加入目标服务器" in response.json()["error_message"]


def test_token_check_warns_when_target_server_is_missing(monkeypatch):
    headers = auth_headers()
    monkeypatch.setattr(discord_manager, "check_discord_token", fake_token_check)
    monkeypatch.setattr(discord_manager, "check_discord_token_guilds", fake_missing_guilds_check)

    server = client.post(
        "/api/targets/servers",
        json={"guild_id": "123456789012345678", "name": "target guild"},
        headers=headers,
    )
    assert server.status_code == 200

    created = client.post(
        "/api/tokens",
        json={"token": "missing-guild-abcdefghijklmnopqrstuvwxyz123456", "note": "guild check"},
        headers=headers,
    )
    assert created.status_code == 200
    assert created.json()["status"] == "standby"
    assert "未加入目标服务器" in created.json()["error_message"]

    logs = client.get("/api/logs", headers=headers)
    assert logs.status_code == 200
    assert any("Token check passed with warning" in item["message"] for item in logs.json())


def test_token_health_skips_future_retry_tokens():
    db = SessionLocal()
    try:
        token = models.DiscordToken(
            token="future-retry-abcdefghijklmnopqrstuvwxyz123456",
            note="retry later",
            status="standby",
            next_retry_at=datetime.utcnow() + timedelta(minutes=20),
            next_check_at=datetime.utcnow() - timedelta(minutes=1),
        )
        db.add(token)
        db.commit()
        db.refresh(token)
        token_id = token.id
    finally:
        db.close()

    due_ids = discord_manager.TokenHealthManager().due_token_ids()
    assert token_id not in due_ids


def test_forwarded_message_can_be_retried_after_failure_or_stale_sending():
    class Obj:
        def __init__(self, id):
            self.id = id

    message = type(
        "Message",
        (),
        {"guild": Obj(123456789012345678), "channel": Obj(234567890123456789), "id": 345678901234567890},
    )()

    db = SessionLocal()
    try:
        assert discord_manager.reserve_forwarded_message(db, message) is True
        assert discord_manager.reserve_forwarded_message(db, message) is False

        discord_manager.mark_forwarded_message(db, message, "failed")
        assert discord_manager.reserve_forwarded_message(db, message) is True

        record = db.query(models.ForwardedMessage).filter(
            models.ForwardedMessage.message_id == discord_manager.forwarded_message_key(message)
        ).first()
        record.created_at = datetime.utcnow() - timedelta(seconds=31)
        db.commit()
        assert discord_manager.reserve_forwarded_message(db, message) is True

        discord_manager.mark_forwarded_message(db, message, "sent")
        assert discord_manager.reserve_forwarded_message(db, message) is False
    finally:
        db.close()


def test_message_image_urls_detects_image_attachments_and_deduplicates():
    attachment = type(
        "Attachment",
        (),
        {"url": "https://cdn.example.com/image.png?size=large", "content_type": "image/png"},
    )()
    duplicate = type(
        "Attachment",
        (),
        {"url": "https://cdn.example.com/image.png?size=large", "content_type": "application/octet-stream"},
    )()
    document = type(
        "Attachment",
        (),
        {"url": "https://cdn.example.com/file.txt", "content_type": "text/plain"},
    )()
    message = type("Message", (), {"attachments": [attachment, duplicate, document], "embeds": []})()

    assert discord_manager.message_image_urls(message) == ["https://cdn.example.com/image.png?size=large"]


def test_photo_caption_is_limited_for_telegram():
    caption = discord_manager.build_photo_caption(
        "owner",
        "sender",
        "channel",
        "x" * 2000,
        None,
        "original",
        False,
    )

    assert len(caption) <= 1024
    assert "图片消息" in caption


def test_stale_forward_result_does_not_overwrite_takeover_record():
    class Obj:
        def __init__(self, id):
            self.id = id

    message = type(
        "Message",
        (),
        {"guild": Obj(123456789012345679), "channel": Obj(234567890123456780), "id": 345678901234567891},
    )()

    db = SessionLocal()
    try:
        assert discord_manager.reserve_forwarded_message(db, message) is True
        original_reserved_at = discord_manager.forwarded_message_reservation_time(db, message)

        record = db.query(models.ForwardedMessage).filter(
            models.ForwardedMessage.message_id == discord_manager.forwarded_message_key(message)
        ).first()
        record.created_at = datetime.utcnow() - timedelta(seconds=31)
        db.commit()

        assert discord_manager.reserve_forwarded_message(db, message) is True
        takeover_reserved_at = discord_manager.forwarded_message_reservation_time(db, message)

        assert discord_manager.mark_forwarded_message(db, message, "failed", original_reserved_at) is False
        db.refresh(record)
        assert record.status == "sending"

        assert discord_manager.mark_forwarded_message(db, message, "sent", takeover_reserved_at) is True
        db.refresh(record)
        assert record.status == "sent"
    finally:
        db.close()


def test_forward_takeover_uses_another_online_client(monkeypatch):
    class Obj:
        def __init__(self, id):
            self.id = id

    class DummyClient:
        def __init__(self, token_id):
            self.token_id = token_id
            self.is_closing = False
            self.calls = []

        def is_ready(self):
            return True

        async def process_message(self, message, **kwargs):
            self.calls.append((message, kwargs))

    message = type(
        "Message",
        (),
        {"guild": Obj(123456789012345680), "channel": Obj(234567890123456781), "id": 345678901234567892},
    )()
    manager = discord_manager.MonitorManager()
    origin = DummyClient(1)
    backup = DummyClient(2)
    manager.active_clients = {1: origin, 2: backup}
    monkeypatch.setattr(manager, "online_token_ids_in_role_order", lambda: [1, 2])

    result = asyncio.run(manager.forward_message_with_another_client(1, message, "live", attempted_token_ids={1}))

    assert result is True
    assert origin.calls == []
    assert len(backup.calls) == 1
    assert backup.calls[0][1]["source"] == "live"
    assert backup.calls[0][1]["attempted_token_ids"] == {1, 2}
