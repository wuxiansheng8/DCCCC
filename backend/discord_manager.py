import asyncio
import html
import logging
import random
from datetime import datetime, timedelta
from typing import Optional

import discord
import httpx
from sqlalchemy.exc import IntegrityError

from ai_service import is_retryable_ai_error, request_chinese_translation, is_google_translate_config
import models
from database import SessionLocal
from maintenance import prune_old_forwarded_messages, prune_old_logs
from telegram_service import send_telegram_message, send_telegram_photo

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = {"standby", "offline", "rate_limited"}
AVAILABLE_STATUSES = {"standby", "online", "offline", "rate_limited"}
HOT_STANDBY_CLIENTS = 2
LOW_POOL_THRESHOLD = 5
TOKEN_CHECK_MIN_HOURS = 6
TOKEN_CHECK_MAX_HOURS = 8
LOW_POOL_ALERT_INTERVAL = timedelta(hours=1)
FORWARD_SEND_TIMEOUT = timedelta(seconds=8)
FORWARD_STALE_AFTER = timedelta(seconds=30)
ONLINE_COVERAGE_FIRST_DELAY = timedelta(minutes=1)
ONLINE_COVERAGE_CHECK_INTERVAL = timedelta(minutes=5)
ONLINE_COVERAGE_FAILURE_RECHECK_DELAY = timedelta(minutes=1)
SERVER_COVERAGE_RETRY_DELAY = timedelta(minutes=30)
ONLINE_COVERAGE_RETRY_DELAYS = (0, 10)
AI_PRIMARY_RECHECK_INTERVAL = timedelta(minutes=30)


def utcnow():
    return datetime.utcnow()


def retry_delay_minutes(failure_count: int) -> int:
    return min(60, 5 * (2 ** max(failure_count - 1, 0)))


def next_token_check_time(now: Optional[datetime] = None):
    now = now or utcnow()
    return now + timedelta(minutes=random.randint(TOKEN_CHECK_MIN_HOURS * 60, TOKEN_CHECK_MAX_HOURS * 60))


def format_alert_time(now: Optional[datetime] = None) -> str:
    now = now or utcnow()
    return (now + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


def token_label(token_obj):
    return token_obj.note or f"Token {token_obj.id}"


def format_target_server(server):
    return f"{server.name} ({server.guild_id})" if server.name else server.guild_id


def make_token_snapshot(token_obj):
    return type(
        "TokenSnapshot",
        (),
        {"id": token_obj.id, "token": token_obj.token, "note": token_obj.note},
    )()


def token_response(token_obj):
    return {
        "id": token_obj.id,
        "token": token_obj.token,
        "note": token_obj.note,
        "status": token_obj.status,
        "last_used": token_obj.last_used,
        "next_retry_at": token_obj.next_retry_at,
        "last_checked_at": token_obj.last_checked_at,
        "next_check_at": token_obj.next_check_at,
        "failure_count": token_obj.failure_count,
        "error_message": token_obj.error_message,
        "created_at": token_obj.created_at,
    }


def forwarded_message_key(message) -> str:
    guild_id = str(message.guild.id) if message.guild else "dm"
    channel_id = str(message.channel.id) if message.channel else "unknown"
    return f"{guild_id}:{channel_id}:{message.id}"


def timestamps_match(left: Optional[datetime], right: Optional[datetime]) -> bool:
    if left is None or right is None:
        return False
    return abs((left - right).total_seconds()) < 0.001


def forwarded_message_reservation_time(db, message) -> Optional[datetime]:
    record = (
        db.query(models.ForwardedMessage)
        .filter(models.ForwardedMessage.message_id == forwarded_message_key(message))
        .first()
    )
    return record.created_at if record else None


def forwarded_message_still_reserved(db, message, reserved_at: Optional[datetime]) -> bool:
    db.expire_all()
    record = (
        db.query(models.ForwardedMessage)
        .filter(models.ForwardedMessage.message_id == forwarded_message_key(message))
        .first()
    )
    return bool(record and record.status == "sending" and timestamps_match(record.created_at, reserved_at))


def reserve_forwarded_message(db, message) -> bool:
    now = utcnow()
    message_id = forwarded_message_key(message)
    record = (
        db.query(models.ForwardedMessage)
        .filter(models.ForwardedMessage.message_id == message_id)
        .first()
    )
    if record:
        if record.status == "sent":
            return False
        if record.status == "sending" and record.created_at > now - FORWARD_STALE_AFTER:
            return False
        record.status = "sending"
        record.created_at = now
        record.sent_at = None
        db.commit()
        return True

    db.add(
        models.ForwardedMessage(
            guild_id=str(message.guild.id) if message.guild else "dm",
            channel_id=str(message.channel.id) if message.channel else "unknown",
            message_id=message_id,
            status="sending",
            created_at=now,
        )
    )
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        record = (
            db.query(models.ForwardedMessage)
            .filter(models.ForwardedMessage.message_id == message_id)
            .first()
        )
        if not record or record.status == "sent":
            return False
        if record.status == "sending" and record.created_at > now - FORWARD_STALE_AFTER:
            return False
        record.status = "sending"
        record.created_at = now
        record.sent_at = None
        db.commit()
        return True


def mark_forwarded_message(db, message, status: str, reserved_at: Optional[datetime] = None) -> bool:
    record = (
        db.query(models.ForwardedMessage)
        .filter(models.ForwardedMessage.message_id == forwarded_message_key(message))
        .first()
    )
    if not record:
        return False
    if reserved_at is not None and not timestamps_match(record.created_at, reserved_at):
        return False
    record.status = status
    if status == "sent":
        record.sent_at = utcnow()
    else:
        record.sent_at = None
    db.commit()
    return True


def normalized_author_username(message) -> str:
    return (getattr(message.author, "name", "") or "").strip().lower()


def author_display_name(message) -> str:
    author = message.author
    return (getattr(author, "name", "") or "").strip() or str(getattr(author, "id", "unknown"))


def channel_label(message, target_channel=None) -> str:
    if target_channel and target_channel.note:
        return target_channel.note
    return getattr(message.channel, "name", None) or str(getattr(message.channel, "id", "unknown"))


HIGHLIGHT_FOOTER = "🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥"
IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def with_highlight_footer(text: str, highlight_enabled: bool) -> str:
    if not highlight_enabled:
        return text
    return f"<b>{text}</b>\n<b>{HIGHLIGHT_FOOTER}</b>"


def is_image_url(url: str) -> bool:
    normalized = (url or "").lower().split("?")[0]
    return normalized.endswith(IMAGE_EXTENSIONS)


def message_image_urls(message) -> list[str]:
    urls = []
    for attachment in getattr(message, "attachments", []) or []:
        url = getattr(attachment, "url", None)
        content_type = (getattr(attachment, "content_type", "") or "").lower()
        if url and (content_type in IMAGE_CONTENT_TYPES or content_type.startswith("image/") or is_image_url(url)):
            urls.append(url)
    for embed in getattr(message, "embeds", []) or []:
        image = getattr(embed, "image", None)
        thumbnail = getattr(embed, "thumbnail", None)
        for media in (image, thumbnail):
            url = getattr(media, "url", None)
            if url and is_image_url(url):
                urls.append(url)
    return list(dict.fromkeys(urls))


def build_forward_text(
    target_name: str,
    display_name: str,
    channel_name: str,
    content: str,
    summary: Optional[str],
    forward_format: str,
    highlight_enabled: bool = False,
) -> str:
    header = (
        f"<b>备注:</b> {html.escape(target_name)}\n"
        f"<b>昵称:</b> {html.escape(display_name)}\n"
        f"<b>频道:</b> {html.escape(channel_name)}\n"
    )
    original_text = html.escape(content or "[empty message]")
    if summary and forward_format == "summary_only":
        return with_highlight_footer(f"{header}<b>中文:</b>\n{html.escape(summary)}", highlight_enabled)
    if summary and forward_format == "summary_original":
        return with_highlight_footer(
            f"{header}<b>中文摘要:</b>\n{html.escape(summary)}\n\n<b>原文:</b>\n{original_text}",
            highlight_enabled,
        )
    return with_highlight_footer(f"{header}<b>内容:</b>\n{original_text}", highlight_enabled)


def build_photo_caption(
    target_name: str,
    display_name: str,
    channel_name: str,
    content: str,
    summary: Optional[str],
    forward_format: str,
    highlight_enabled: bool = False,
) -> str:
    text = build_forward_text(
        target_name,
        display_name,
        channel_name,
        content,
        summary,
        forward_format,
        highlight_enabled,
    )
    if len(text) <= 1024:
        return text
    header = (
        f"<b>备注:</b> {html.escape(target_name)}\n"
        f"<b>昵称:</b> {html.escape(display_name)}\n"
        f"<b>频道:</b> {html.escape(channel_name)}\n"
    )
    if summary:
        caption = f"{header}<b>中文:</b>\n{html.escape(summary)}"
    else:
        caption = f"{header}<b>图片消息</b>"
    caption = with_highlight_footer(caption, highlight_enabled)
    return caption[:1024]


def resolve_target_user(db, author_id: str, username: str):
    target_user = db.query(models.TargetUser).filter(models.TargetUser.user_id == author_id).first()
    if target_user:
        return target_user

    if not username:
        return None

    target_user = db.query(models.TargetUser).filter(models.TargetUser.username == username).first()
    if not target_user:
        return None

    if target_user.user_id:
        return target_user if target_user.user_id == author_id else None

    if not target_user.user_id:
        target_user.user_id = author_id
        db.add(models.SystemLog(level="success", message=f"Locked target username {username} to user ID {author_id}."))
        db.commit()
        return target_user

    return target_user


async def log_to_db(level, message):
    db = SessionLocal()
    try:
        db.add(models.SystemLog(level=level, message=message))
        db.commit()
        prune_old_logs(db)
        prune_old_forwarded_messages(db)
    finally:
        db.close()


def has_backup_ai_config(config: models.SystemConfig) -> bool:
    return bool(config.ai_backup_api_key and config.ai_backup_base_url and config.ai_backup_model)


async def generate_chinese_summary_with_failover(config: models.SystemConfig, message_text: str):
    now = utcnow()
    provider = config.ai_active_provider or "primary"
    has_backup = has_backup_ai_config(config)

    if provider == "backup" and has_backup:
        should_check_primary = config.ai_primary_next_check_at is None or config.ai_primary_next_check_at <= now
        is_google = is_google_translate_config(config.ai_api_key, config.ai_base_url, config.ai_model)
        if should_check_primary and (config.ai_api_key or is_google) and (config.ai_base_url or is_google) and config.ai_model:
            summary, error, status_code = await request_chinese_translation(
                config.ai_api_key,
                config.ai_base_url,
                config.ai_model,
                message_text,
            )
            if not error:
                config.ai_active_provider = "primary"
                config.ai_primary_next_check_at = None
                return summary, None, "primary", "AI primary provider recovered; switched back to primary."
            config.ai_primary_next_check_at = now + AI_PRIMARY_RECHECK_INTERVAL

    if provider == "backup" and has_backup:
        summary, error, _status_code = await request_chinese_translation(
            config.ai_backup_api_key,
            config.ai_backup_base_url,
            config.ai_backup_model,
            message_text,
        )
        return summary, error, "backup", None

    is_google = is_google_translate_config(config.ai_api_key, config.ai_base_url, config.ai_model)
    summary, error, status_code = await request_chinese_translation(
        config.ai_api_key,
        config.ai_base_url or ("" if is_google else "https://api.deepseek.com"),
        config.ai_model or ("google" if is_google else "deepseek-chat"),
        message_text,
    )
    if not error or not has_backup or not is_retryable_ai_error(error, status_code):
        return summary, error, "primary", None

    backup_summary, backup_error, _backup_status_code = await request_chinese_translation(
        config.ai_backup_api_key,
        config.ai_backup_base_url,
        config.ai_backup_model,
        message_text,
    )
    if not backup_error:
        config.ai_active_provider = "backup"
        config.ai_primary_next_check_at = now + AI_PRIMARY_RECHECK_INTERVAL
        return backup_summary, None, "backup", f"AI primary provider failed ({error}); switched to backup."
    return None, f"Primary AI failed: {error}; backup AI failed: {backup_error}", "primary", None


async def run_due_ai_primary_check():
    db = SessionLocal()
    try:
        config = db.query(models.SystemConfig).first()
        if not config:
            return
        now = utcnow()
        is_google = is_google_translate_config(config.ai_api_key, config.ai_base_url, config.ai_model)
        if (
            config.ai_active_provider != "backup"
            or not has_backup_ai_config(config)
            or (not config.ai_api_key and not is_google)
            or (not config.ai_base_url and not is_google)
            or not config.ai_model
            or (config.ai_primary_next_check_at and config.ai_primary_next_check_at > now)
        ):
            return

        summary, error, _status_code = await request_chinese_translation(
            config.ai_api_key,
            config.ai_base_url,
            config.ai_model,
            "Connection test.",
        )
        if not error and summary:
            config.ai_active_provider = "primary"
            config.ai_primary_next_check_at = None
            db.add(models.SystemLog(level="success", message="AI primary provider recovered; switched back to primary."))
        else:
            config.ai_primary_next_check_at = now + AI_PRIMARY_RECHECK_INTERVAL
            db.add(models.SystemLog(level="warning", message=f"AI primary provider still unavailable: {error}"))
        db.commit()
        prune_old_logs(db)
    finally:
        db.close()


async def send_service_alert(title: str, body: str, level: str = "info"):
    db = SessionLocal()
    try:
        config = db.query(models.SystemConfig).first()
        if not config or not config.tg_bot_token or not config.tg_chat_id:
            return
        bot_token = config.tg_bot_token
        chat_id = config.tg_chat_id
    finally:
        db.close()

    text = (
        f"<b>[DC Monitor] {html.escape(title)}</b>\n"
        f"{html.escape(body)}\n"
        f"<b>时间:</b> {format_alert_time()}"
    )
    success, error = await send_telegram_message(bot_token, chat_id, text)
    if not success:
        await log_to_db(level, f"Failed to send service alert: {error}")


async def check_discord_token(token_obj):
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                "https://discord.com/api/v10/users/@me",
                headers={
                    "Authorization": token_obj.token,
                    "User-Agent": "Mozilla/5.0 DC-TG-Monitor",
                },
            )

        if response.status_code == 200:
            return "standby", None
        if response.status_code in {401, 403}:
            return "invalid", "Discord rejected the token."
        if response.status_code == 429:
            return "rate_limited", "Discord rate limited token validation."
        return "offline", f"Discord token validation returned HTTP {response.status_code}."
    except httpx.TimeoutException:
        return "offline", "Discord token validation timed out."
    except httpx.RequestError as exc:
        return "offline", f"Discord token validation request failed: {exc}"
    except Exception as exc:
        return "offline", f"Token check failed: {exc}"


async def check_discord_token_guilds(token_obj):
    try:
        guild_ids = set()
        after = None
        async with httpx.AsyncClient(timeout=15) as client:
            while True:
                params = {"limit": 200}
                if after:
                    params["after"] = after
                response = await client.get(
                    "https://discord.com/api/v10/users/@me/guilds",
                    headers={
                        "Authorization": token_obj.token,
                        "User-Agent": "Mozilla/5.0 DC-TG-Monitor",
                    },
                    params=params,
                )

                if response.status_code == 429:
                    return None, "Discord rate limited server membership check."
                if response.status_code in {401, 403}:
                    return None, "Discord rejected server membership check."
                if response.status_code != 200:
                    return None, f"Discord server membership check returned HTTP {response.status_code}."

                guilds = response.json()
                guild_ids.update(str(guild.get("id")) for guild in guilds if guild.get("id"))
                if len(guilds) < 200:
                    return guild_ids, None
                after = guilds[-1].get("id")
                if not after:
                    return guild_ids, None
    except httpx.TimeoutException:
        return None, "Discord server membership check timed out."
    except httpx.RequestError as exc:
        return None, f"Discord server membership check request failed: {exc}"
    except Exception as exc:
        return None, f"Server membership check failed: {exc}"


async def check_token_server_coverage(token_obj):
    target_servers = get_target_server_snapshots()
    if not target_servers:
        return None, None

    guild_ids, membership_error = await check_discord_token_guilds(token_obj)
    if membership_error:
        return None, membership_error

    missing_servers = [
        server for server in target_servers if server.guild_id not in guild_ids
    ]
    if not missing_servers:
        return None, None

    missing_labels = ", ".join(format_target_server(server) for server in missing_servers)
    return f"{token_label(token_obj)} 未加入目标服务器：{missing_labels}", None


def get_target_server_snapshots():
    db = SessionLocal()
    try:
        return [
            type(
                "TargetServerSnapshot",
                (),
                {"guild_id": server.guild_id, "name": server.name},
            )()
            for server in db.query(models.TargetServer).order_by(models.TargetServer.id.asc()).all()
        ]
    finally:
        db.close()


async def run_token_check(token_id: int, manual: bool = False):
    db = SessionLocal()
    try:
        token_obj = db.query(models.DiscordToken).filter(models.DiscordToken.id == token_id).first()
        if not token_obj:
            return None
        if token_obj.status == "online":
            return token_response(token_obj)
        token_snapshot = make_token_snapshot(token_obj)
    finally:
        db.close()

    status, error = await check_discord_token(token_snapshot)
    membership_warning = None
    if status == "standby":
        membership_warning, membership_error = await check_token_server_coverage(token_snapshot)
        if membership_error:
            membership_warning = membership_error
    now = utcnow()

    db = SessionLocal()
    try:
        token_obj = db.query(models.DiscordToken).filter(models.DiscordToken.id == token_id).first()
        if not token_obj:
            return None
        if token_obj.status != "online":
            token_obj.status = status
        token_obj.last_checked_at = now
        token_obj.next_check_at = next_token_check_time(now)
        token_obj.last_used = now

        if status == "standby":
            token_obj.failure_count = 0
            token_obj.next_retry_at = None
            token_obj.error_message = membership_warning
            level = "warning" if membership_warning else "success"
            message = (
                f"Token check passed with warning: {token_label(token_obj)} - {membership_warning}"
                if membership_warning
                else f"Token check passed: {token_label(token_obj)}."
            )
        else:
            token_obj.error_message = error
            if status in {"offline", "rate_limited"}:
                token_obj.failure_count = (token_obj.failure_count or 0) + 1
                token_obj.next_retry_at = now + timedelta(minutes=retry_delay_minutes(token_obj.failure_count))
            else:
                token_obj.next_retry_at = None
            level = "error" if status == "invalid" else "warning"
            message = f"Token check failed: {token_label(token_obj)} - {error}"

        if manual:
            message = f"Manual {message[0].lower()}{message[1:]}"
        db.add(models.SystemLog(level=level, message=message))
        db.commit()
        db.refresh(token_obj)
        response = token_response(token_obj)
        prune_old_logs(db)
        prune_old_forwarded_messages(db)
        return response
    finally:
        db.close()


class TokenHealthManager:
    def __init__(self):
        self.task = None
        self.should_run = False
        self.last_low_pool_alert_at = None

    async def start(self):
        self.should_run = True
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self.run_loop())

    async def stop(self):
        self.should_run = False
        if self.task and not self.task.done():
            self.task.cancel()

    def is_worker_running(self):
        return bool(self.task and not self.task.done())

    def due_token_ids(self):
        db = SessionLocal()
        try:
            now = utcnow()
            tokens = db.query(models.DiscordToken).filter(models.DiscordToken.status != "disabled").all()
            due_ids = []
            for token in tokens:
                if token.status == "online":
                    continue
                if token.next_retry_at is not None and token.next_retry_at > now:
                    continue
                if token.next_check_at is None:
                    token.next_check_at = next_token_check_time(now)
                elif token.next_check_at <= now:
                    due_ids.append(token.id)
            db.commit()
            return due_ids
        finally:
            db.close()

    async def send_low_pool_alert_if_needed(self):
        db = SessionLocal()
        try:
            now = utcnow()
            available_count = db.query(models.DiscordToken).filter(models.DiscordToken.status.in_(AVAILABLE_STATUSES)).count()
            config = db.query(models.SystemConfig).first()
            if available_count >= LOW_POOL_THRESHOLD:
                return
            if self.last_low_pool_alert_at and now - self.last_low_pool_alert_at < LOW_POOL_ALERT_INTERVAL:
                return
            if not config or not config.tg_bot_token or not config.tg_chat_id:
                db.add(models.SystemLog(level="warning", message="Token pool is low, but Telegram is not configured."))
                db.commit()
                prune_old_logs(db)
                self.last_low_pool_alert_at = now
                return
            bot_token = config.tg_bot_token
            chat_id = config.tg_chat_id
        finally:
            db.close()

        alert_text = (
            "🚨🚨🚨 <b>号池不足请补充！！</b>\n"
            f"当前可用账号：{available_count}\n"
            f"最低要求：{LOW_POOL_THRESHOLD}"
        )
        for _ in range(3):
            await send_telegram_message(bot_token, chat_id, alert_text)
            await asyncio.sleep(1)
        self.last_low_pool_alert_at = utcnow()
        await log_to_db("warning", f"Low token pool alert sent. Available tokens: {available_count}.")

    async def run_loop(self):
        while self.should_run:
            try:
                for token_id in self.due_token_ids():
                    await run_token_check(token_id)
                    await asyncio.sleep(3)
                await self.send_low_pool_alert_if_needed()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Token health worker failed: %s", exc)
                await log_to_db("error", f"Token health worker failed: {exc}")
            await asyncio.sleep(60)


class DiscordMonitor(discord.Client):
    def __init__(self, token_id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.token_id = token_id
        self.token_value = None
        self.is_closing = False

    async def on_ready(self):
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        await self.update_db_status("online")
        await self.log_to_db("success", f"DC Account {self.user.name} is online and monitoring.")
        if not await monitor_manager.handle_online_client_ready(self):
            return
        await self.backfill_recent_messages()

    async def on_message(self, message):
        if self.user and message.author.id == self.user.id:
            return

        await self.process_message(message, source="live")

    async def backfill_recent_messages(self):
        db = SessionLocal()
        try:
            target_server_ids = {row.guild_id for row in db.query(models.TargetServer.guild_id).all()}
            target_user_ids = {
                row.user_id for row in db.query(models.TargetUser.user_id).all() if row.user_id
            }
            target_usernames = {
                row.username for row in db.query(models.TargetUser.username).all() if row.username
            }
        finally:
            db.close()

        if not target_server_ids or (not target_user_ids and not target_usernames):
            return

        cutoff = utcnow() - timedelta(minutes=1)
        logger.info("Starting 1-minute backfill for token %s", self.token_id)
        for guild in (self.guilds or []):
            if str(guild.id) not in target_server_ids:
                continue
            forbidden_channels = []
            failed_channels = []
            for channel in getattr(guild, "text_channels", []):
                try:
                    async for message in channel.history(after=cutoff, oldest_first=True, limit=None):
                        await self.process_message(
                            message,
                            source="backfill",
                            target_server_ids=target_server_ids,
                            target_user_ids=target_user_ids,
                            target_usernames=target_usernames,
                        )
                except discord.Forbidden:
                    forbidden_channels.append(getattr(channel, "name", str(getattr(channel, "id", "unknown"))))
                except discord.HTTPException as exc:
                    failed_channels.append(f"{getattr(channel, 'name', 'unknown')}: {exc}")
            if forbidden_channels:
                sample = "、".join(forbidden_channels[:5])
                suffix = f" 等 {len(forbidden_channels)} 个频道" if len(forbidden_channels) > 5 else ""
                await self.log_to_db("warning", f"回补已跳过：{guild.name} / {sample}{suffix}，权限不足")
            if failed_channels:
                sample = "；".join(failed_channels[:3])
                suffix = f" 等 {len(failed_channels)} 个频道" if len(failed_channels) > 3 else ""
                await self.log_to_db("warning", f"回补失败：{guild.name} / {sample}{suffix}")

    async def process_message(
        self,
        message,
        source: str = "live",
        target_server_ids=None,
        target_user_ids=None,
        target_usernames=None,
        attempted_token_ids=None,
    ):
        if not message.guild or not message.channel:
            return

        guild_id = str(message.guild.id)
        author_id = str(message.author.id)
        author_username = normalized_author_username(message)

        if target_server_ids is not None and guild_id not in target_server_ids:
            return
        if target_user_ids is not None and target_usernames is not None:
            if author_id not in target_user_ids and author_username not in target_usernames:
                return
        elif target_user_ids is not None and author_id not in target_user_ids:
            return
        elif target_usernames is not None and author_username not in target_usernames:
            return

        db = SessionLocal()
        try:
            is_target_server = db.query(models.TargetServer).filter(models.TargetServer.guild_id == guild_id).first()
            target_user = resolve_target_user(db, author_id, author_username)
            target_channel = db.query(models.TargetChannel).filter(models.TargetChannel.channel_id == str(message.channel.id)).first()

            if not (is_target_server and target_user):
                return

            config = db.query(models.SystemConfig).first()
            if not config or not config.tg_bot_token or not config.tg_chat_id:
                await self.log_to_db("warning", "Matched a target message, but Telegram is not configured.")
                return

            if not reserve_forwarded_message(db, message):
                return
            reservation_started_at = forwarded_message_reservation_time(db, message)
            attempted_token_ids = set(attempted_token_ids or [])
            attempted_token_ids.add(self.token_id)
            message_key = forwarded_message_key(message)

            author_name = message.author.name
            display_name = author_display_name(message)
            raw_content = (message.content or "").strip()
            content = raw_content or "[empty message]"
            image_urls = message_image_urls(message)
            target_name = target_user.note or target_user.username or author_name
            channel_name = channel_label(message, target_channel)

            summary = None
            forward_format = config.ai_forward_format or "summary_original"
            if raw_content and config.ai_enabled and forward_format != "original":
                is_google = is_google_translate_config(config.ai_api_key, config.ai_base_url, config.ai_model)
                if config.ai_api_key or is_google:
                    summary, summary_error, _ai_provider, switch_message = await generate_chinese_summary_with_failover(
                        config,
                        raw_content,
                    )
                    if switch_message:
                        db.add(models.SystemLog(level="warning", message=f"{switch_message} message_id={message_key}"))
                        db.commit()
                    if summary_error:
                        await self.log_to_db("warning", f"AI summary failed for message_id={message_key}: {summary_error}")
                else:
                    await self.log_to_db("warning", f"AI summary is enabled, but API key is not configured. message_id={message_key}")

            text = build_forward_text(
                target_name,
                display_name,
                channel_name,
                content,
                summary,
                forward_format,
                target_user.highlight_enabled,
            )
            photo_caption = build_photo_caption(
                target_name,
                display_name,
                channel_name,
                content,
                summary,
                forward_format,
                target_user.highlight_enabled,
            )
            if not forwarded_message_still_reserved(db, message, reservation_started_at):
                await self.log_to_db(
                    "warning",
                    f"Stopped stale forward attempt from Token {self.token_id} for message_id={message_key} because another token took over.",
                )
                return

            message_url = None
            if message.guild and message.channel:
                message_url = f"https://discord.com/channels/{message.guild.id}/{message.channel.id}/{message.id}"

            try:
                if image_urls:
                    if len(image_urls) == 1:
                        success, error = await asyncio.wait_for(
                            send_telegram_photo(
                                config.tg_bot_token,
                                config.tg_chat_id,
                                image_urls[0],
                                photo_caption,
                                message_url=message_url,
                            ),
                            timeout=FORWARD_SEND_TIMEOUT.total_seconds(),
                        )
                    else:
                        success, error = await asyncio.wait_for(
                            send_telegram_photo(
                                config.tg_bot_token,
                                config.tg_chat_id,
                                image_urls[0],
                                photo_caption,
                            ),
                            timeout=FORWARD_SEND_TIMEOUT.total_seconds(),
                        )
                        if success:
                            for idx, image_url in enumerate(image_urls[1:], 1):
                                is_last = (idx == len(image_urls) - 1)
                                success, error = await asyncio.wait_for(
                                    send_telegram_photo(
                                        config.tg_bot_token,
                                        config.tg_chat_id,
                                        image_url,
                                        message_url=message_url if is_last else None,
                                    ),
                                    timeout=FORWARD_SEND_TIMEOUT.total_seconds(),
                                )
                                if not success:
                                    break
                else:
                    success, error = await asyncio.wait_for(
                        send_telegram_message(
                            config.tg_bot_token,
                            config.tg_chat_id,
                            text,
                            message_url=message_url,
                        ),
                        timeout=FORWARD_SEND_TIMEOUT.total_seconds(),
                    )
            except asyncio.TimeoutError:
                success = False
                error = f"Telegram send did not finish within {int(FORWARD_SEND_TIMEOUT.total_seconds())} seconds"
            except Exception as exc:
                success = False
                error = str(exc)

            if success:
                config.last_forwarded_at = utcnow()
                config.last_error = None
                if mark_forwarded_message(db, message, "sent", reservation_started_at):
                    db.commit()
                    media_suffix = f" with {len(image_urls)} image(s)" if image_urls else ""
                    await self.log_to_db(
                        "info",
                        f"Forwarded {source} message_id={message_key}{media_suffix} from {target_name} in {channel_name}.",
                    )
                else:
                    db.rollback()
                    await self.log_to_db(
                        "warning",
                        f"Ignored stale forward success from Token {self.token_id} for message_id={message_key}.",
                    )
            else:
                config.last_error = error
                if mark_forwarded_message(db, message, "failed", reservation_started_at):
                    db.commit()
                    await self.log_to_db("error", f"Failed to forward message_id={message_key} from {author_name}: {error}")
                    await monitor_manager.forward_message_with_another_client(
                        self.token_id,
                        message,
                        source,
                        attempted_token_ids=attempted_token_ids,
                    )
                else:
                    db.rollback()
                    await self.log_to_db(
                        "warning",
                        f"Ignored stale forward failure from Token {self.token_id} for message_id={message_key}.",
                    )
        finally:
            db.close()

    async def on_error(self, event, *args, **kwargs):
        logger.exception("Discord error in %s", event)
        await self.log_to_db("error", f"Discord error in {event}.")

    async def update_db_status(self, status, error_msg: Optional[str] = None):
        should_alert_online = False
        db = SessionLocal()
        try:
            now = utcnow()
            token_obj = db.query(models.DiscordToken).filter(models.DiscordToken.id == self.token_id).first()
            config = db.query(models.SystemConfig).first()
            if token_obj:
                token_obj.status = status
                token_obj.last_used = now
                if status == "online":
                    token_obj.failure_count = 0
                    token_obj.next_retry_at = None
                    token_obj.error_message = None
                elif error_msg:
                    token_obj.error_message = error_msg
            if config:
                if status == "online" and config.active_token_id is None:
                    config.active_token_id = self.token_id
                elif status != "online" and config.active_token_id == self.token_id:
                    config.active_token_id = None
                config.last_heartbeat_at = now
                if status == "online":
                    if config.stable_uptime_started_at is None:
                        config.stable_uptime_started_at = now
                        should_alert_online = True
                    config.last_error = None
                elif config.active_token_id is None:
                    config.stable_uptime_started_at = None
                if error_msg:
                    config.last_error = error_msg
            db.commit()
        finally:
            db.close()
        if should_alert_online:
            await send_service_alert("服务已上线", f"监控服务已恢复运行，当前 Token ID: {self.token_id}。")

    async def log_to_db(self, level, message):
        db = SessionLocal()
        try:
            db.add(models.SystemLog(level=level, message=message))
            db.commit()
            prune_old_logs(db)
            prune_old_forwarded_messages(db)
        finally:
            db.close()


class MonitorManager:
    def __init__(self):
        self.active_clients = {}
        self.client_tasks = {}
        self.should_run = False
        self.task = None
        self.next_online_coverage_check_at = None
        self.online_coverage_index = 0

    def is_worker_running(self):
        return bool(self.task and not self.task.done())

    async def start(self):
        self.should_run = True
        if self.next_online_coverage_check_at is None:
            self.next_online_coverage_check_at = utcnow() + ONLINE_COVERAGE_FIRST_DELAY
        self.persist_state(is_running=True, started=True)
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self.run_loop())

    async def stop(self):
        self.should_run = False
        for client in list(self.active_clients.values()):
            client.is_closing = True
            await client.close()
        tasks = list(self.client_tasks.values())
        for task in list(self.client_tasks.values()):
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.next_online_coverage_check_at = None
        self.online_coverage_index = 0
        self.persist_state(is_running=False, stopped=True, clear_active=True)
        await log_to_db("info", "System monitoring stopped.")

    def persist_state(self, is_running: bool, started: bool = False, stopped: bool = False, clear_active: bool = False):
        db = SessionLocal()
        try:
            config = db.query(models.SystemConfig).first()
            now = utcnow()
            if config:
                config.is_running = is_running
                config.last_heartbeat_at = now
                if started:
                    config.last_started_at = now
                    config.stable_uptime_started_at = None
                if stopped:
                    config.last_stopped_at = now
                    config.stable_uptime_started_at = None
                if clear_active:
                    config.active_token_id = None
                    online_tokens = db.query(models.DiscordToken).filter(models.DiscordToken.status == "online").all()
                    for token in online_tokens:
                        token.status = "offline"
            db.commit()
        finally:
            db.close()

    def select_next_tokens(self, limit: int, exclude_ids=None):
        exclude_ids = set(exclude_ids or [])
        db = SessionLocal()
        try:
            now = utcnow()
            candidates = db.query(models.DiscordToken).filter(models.DiscordToken.status.in_(RETRYABLE_STATUSES)).all()
            candidates = [
                token
                for token in candidates
                if token.id not in exclude_ids and (token.next_retry_at is None or token.next_retry_at <= now)
            ]
            if not candidates:
                return []
            candidates.sort(key=lambda token: (token.last_used is not None, token.last_used or datetime.min, token.id))
            return [(token.id, token.token) for token in candidates[:limit]]
        finally:
            db.close()

    async def mark_token_failure(self, token_id: int, status: str, message: str):
        fallback_token_id = None
        service_unavailable = False
        db = SessionLocal()
        try:
            now = utcnow()
            token_obj = db.query(models.DiscordToken).filter(models.DiscordToken.id == token_id).first()
            config = db.query(models.SystemConfig).first()
            if token_obj:
                token_obj.status = status
                token_obj.last_used = now
                token_obj.error_message = message
                if status in {"offline", "rate_limited"}:
                    token_obj.failure_count = (token_obj.failure_count or 0) + 1
                    token_obj.next_retry_at = now + timedelta(minutes=retry_delay_minutes(token_obj.failure_count))
                else:
                    token_obj.next_retry_at = None
            if config:
                if config.active_token_id == token_id:
                    config.active_token_id = None
                    fallback_token = (
                        db.query(models.DiscordToken)
                        .filter(models.DiscordToken.status == "online", models.DiscordToken.id != token_id)
                        .order_by(models.DiscordToken.id.asc())
                        .first()
                    )
                    if fallback_token:
                        config.active_token_id = fallback_token.id
                        fallback_token_id = fallback_token.id
                        db.add(models.SystemLog(level="warning", message=f"Token switch: {token_id} -> {fallback_token_id}."))
                    else:
                        service_unavailable = True
                config.last_heartbeat_at = now
                config.last_error = message
                if service_unavailable:
                    config.stable_uptime_started_at = None
            db.add(models.SystemLog(level="error", message=f"Token {token_id}: {message}"))
            if service_unavailable:
                db.add(models.SystemLog(level="error", message=f"Service unavailable: {message}"))
            db.commit()
            prune_old_logs(db)
            prune_old_forwarded_messages(db)
        finally:
            db.close()
        if service_unavailable:
            await send_service_alert("服务不可用", f"监控服务已断开：{message}", level="error")
        if fallback_token_id:
            await self.check_online_client_by_id(fallback_token_id, full_health=True, reason="active fallback")

    def online_token_ids_in_role_order(self):
        db = SessionLocal()
        try:
            config = db.query(models.SystemConfig).first()
            active_token_id = config.active_token_id if config else None
        finally:
            db.close()

        ready_ids = [
            token_id
            for token_id, client in self.active_clients.items()
            if not client.is_closing and client.is_ready()
        ]
        ordered_ids = []
        if active_token_id in ready_ids:
            ordered_ids.append(active_token_id)
        ordered_ids.extend(sorted(token_id for token_id in ready_ids if token_id != active_token_id))
        return ordered_ids

    async def forward_message_with_another_client(self, origin_token_id: int, message, source: str, attempted_token_ids=None):
        attempted_token_ids = set(attempted_token_ids or [])
        attempted_token_ids.add(origin_token_id)

        for token_id in self.online_token_ids_in_role_order():
            if token_id in attempted_token_ids:
                continue
            client = self.active_clients.get(token_id)
            if not client or client.is_closing or not client.is_ready():
                continue

            await log_to_db(
                "warning",
                f"Forward retry triggered for message {forwarded_message_key(message)} from Token {origin_token_id} to Token {token_id}.",
            )
            await client.process_message(
                message,
                source=source,
                attempted_token_ids=attempted_token_ids | {token_id},
            )
            return True

        await log_to_db(
            "warning",
            f"Forward retry skipped for message {forwarded_message_key(message)} because no other online token is available.",
        )
        return False

    def online_token_snapshot(self, client):
        db = SessionLocal()
        try:
            token_obj = db.query(models.DiscordToken).filter(models.DiscordToken.id == client.token_id).first()
            note = token_obj.note if token_obj else None
        finally:
            db.close()
        return type(
            "TokenSnapshot",
            (),
            {"id": client.token_id, "token": client.token_value, "note": note},
        )()

    async def close_client_for_replacement(self, client):
        client.is_closing = True
        await client.close()

    async def release_token_missing_coverage(self, token_id: int, message: str):
        fallback_token_id = None
        service_unavailable = False
        db = SessionLocal()
        try:
            now = utcnow()
            token_obj = db.query(models.DiscordToken).filter(models.DiscordToken.id == token_id).first()
            config = db.query(models.SystemConfig).first()
            if token_obj:
                token_obj.status = "standby"
                token_obj.error_message = message
                token_obj.last_checked_at = now
                token_obj.last_used = now
                token_obj.next_retry_at = now + SERVER_COVERAGE_RETRY_DELAY
                token_obj.next_check_at = now + SERVER_COVERAGE_RETRY_DELAY
            if config:
                if config.active_token_id == token_id:
                    config.active_token_id = None
                    fallback_token = (
                        db.query(models.DiscordToken)
                        .filter(models.DiscordToken.status == "online", models.DiscordToken.id != token_id)
                        .order_by(models.DiscordToken.id.asc())
                        .first()
                    )
                    if fallback_token:
                        config.active_token_id = fallback_token.id
                        fallback_token_id = fallback_token.id
                        db.add(models.SystemLog(level="warning", message=f"Token switch: {token_id} -> {fallback_token_id}."))
                    else:
                        service_unavailable = True
                config.last_heartbeat_at = now
                config.last_error = message
                if service_unavailable:
                    config.stable_uptime_started_at = None
            db.add(models.SystemLog(level="warning", message=f"Token {token_id}: {message}"))
            if service_unavailable:
                db.add(models.SystemLog(level="error", message=f"Service unavailable: {message}"))
            db.commit()
            prune_old_logs(db)
            prune_old_forwarded_messages(db)
        finally:
            db.close()
        if service_unavailable:
            await send_service_alert("服务不可用", f"监控服务已断开：{message}", level="error")
        return fallback_token_id

    async def check_online_client_by_id(self, token_id: int, full_health: bool, reason: str):
        client = self.active_clients.get(token_id)
        if not client or client.is_closing or not client.is_ready():
            return False
        return await self.check_online_client(client, full_health=full_health, reason=reason)

    async def check_online_client(self, client, full_health: bool, reason: str):
        if not client.token_value:
            await log_to_db("warning", f"Online token coverage check skipped for Token {client.token_id}: token value is unavailable.")
            return True

        token_snapshot = self.online_token_snapshot(client)
        if full_health:
            status, error = await check_discord_token(token_snapshot)
            if status == "invalid":
                await self.mark_token_failure(client.token_id, "invalid", error or "Token is invalid.")
                await self.close_client_for_replacement(client)
                return False
            if status != "standby":
                await log_to_db(
                    "warning",
                    f"Online token health check failed during {reason}: {token_label(token_snapshot)} - {error}",
                )

        coverage_warning = None
        coverage_error = None
        for attempt, delay_seconds in enumerate(ONLINE_COVERAGE_RETRY_DELAYS):
            if delay_seconds:
                await asyncio.sleep(delay_seconds)
            coverage_warning, coverage_error = await check_token_server_coverage(token_snapshot)
            if not coverage_error:
                break
            if attempt < len(ONLINE_COVERAGE_RETRY_DELAYS) - 1:
                await log_to_db(
                    "warning",
                    f"Online token server coverage check retrying during {reason}: {token_label(token_snapshot)} - {coverage_error}",
                )
        if coverage_error:
            await log_to_db(
                "warning",
                f"Online token server coverage check failed during {reason}: {token_label(token_snapshot)} - {coverage_error}",
            )
            self.next_online_coverage_check_at = min(
                self.next_online_coverage_check_at or utcnow() + ONLINE_COVERAGE_FAILURE_RECHECK_DELAY,
                utcnow() + ONLINE_COVERAGE_FAILURE_RECHECK_DELAY,
            )
            return True
        if coverage_warning:
            fallback_token_id = await self.release_token_missing_coverage(client.token_id, coverage_warning)
            await self.close_client_for_replacement(client)
            if fallback_token_id:
                await self.check_online_client_by_id(fallback_token_id, full_health=True, reason="coverage fallback")
            return False

        return True

    async def handle_online_client_ready(self, client):
        return await self.check_online_client(client, full_health=True, reason="online startup")

    async def run_due_online_coverage_check(self):
        now = utcnow()
        if self.next_online_coverage_check_at is None:
            self.next_online_coverage_check_at = now + ONLINE_COVERAGE_FIRST_DELAY
            return
        if now < self.next_online_coverage_check_at:
            return

        ordered_ids = self.online_token_ids_in_role_order()
        if not ordered_ids:
            self.online_coverage_index = 0
            self.next_online_coverage_check_at = now + ONLINE_COVERAGE_FIRST_DELAY
            return

        index = self.online_coverage_index % len(ordered_ids)
        token_id = ordered_ids[index]
        self.online_coverage_index = (index + 1) % len(ordered_ids)
        await self.check_online_client_by_id(token_id, full_health=False, reason="scheduled online rotation")
        self.next_online_coverage_check_at = utcnow() + ONLINE_COVERAGE_CHECK_INTERVAL

    async def run_client(self, token_id: int, token_value: str):
        client = DiscordMonitor(token_id=token_id)
        client.token_value = token_value
        self.active_clients[token_id] = client
        try:
            await client.start(token_value)
            if self.should_run and not client.is_closing:
                await self.mark_token_failure(token_id, "offline", "Discord client disconnected.")
        except discord.LoginFailure:
            if self.should_run and not client.is_closing:
                await self.mark_token_failure(token_id, "invalid", "Login failed. Token is invalid.")
        except discord.HTTPException as exc:
            if self.should_run and not client.is_closing:
                status = "rate_limited" if getattr(exc, "status", None) == 429 else "offline"
                await self.mark_token_failure(token_id, status, f"Discord HTTP error: {exc}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Client crashed")
            if self.should_run and not client.is_closing:
                await self.mark_token_failure(token_id, "offline", f"Discord client crashed: {exc}")
        finally:
            self.active_clients.pop(token_id, None)
            self.client_tasks.pop(token_id, None)

    async def run_loop(self):
        while self.should_run:
            running_ids = set(self.active_clients.keys()) | set(self.client_tasks.keys())
            needed = HOT_STANDBY_CLIENTS - len(running_ids)
            if needed > 0:
                selected_tokens = self.select_next_tokens(needed, exclude_ids=running_ids)
                if not selected_tokens:
                    logger.warning("No available tokens found. Waiting 60 seconds...")
                    if not running_ids:
                        self.persist_state(is_running=True)
                        await run_due_ai_primary_check()
                        await asyncio.sleep(60)
                        continue
                for token_id, token_value in selected_tokens:
                    self.client_tasks[token_id] = asyncio.create_task(self.run_client(token_id, token_value))
            await self.run_due_online_coverage_check()
            await run_due_ai_primary_check()
            self.persist_state(is_running=True)
            await asyncio.sleep(10)


monitor_manager = MonitorManager()
token_health_manager = TokenHealthManager()
