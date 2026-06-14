import logging
import os
from datetime import datetime, timedelta
from typing import List

from fastapi import Body, Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import jwt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import models
import schemas
from ai_service import get_api_balance, request_chinese_translation, is_google_translate_config
from database import SessionLocal, engine, get_db
from discord_manager import generate_chinese_summary_with_failover, monitor_manager, run_token_check, token_health_manager
from maintenance import prune_old_logs
from telegram_service import send_telegram_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Discord-to-Telegram Monitor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/login")


def ensure_config(db: Session) -> models.SystemConfig:
    config = db.query(models.SystemConfig).first()
    if not config:
        config = models.SystemConfig()
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def hour_floor(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def is_runtime_start_log(message: str) -> bool:
    return message.startswith("DC Account ") and message.endswith(" is online and monitoring.")


def is_runtime_stop_log(message: str) -> bool:
    return (
        message == "System monitoring stopped."
        or message == "System monitoring interrupted by backend restart."
        or message.startswith("Service unavailable:")
    )


def is_token_switch_log(message: str) -> bool:
    return message.startswith("Token switch:")


def overlap_seconds(start: datetime, end: datetime, left: datetime, right: datetime) -> int:
    overlap_start = max(start, left)
    overlap_end = min(end, right)
    if overlap_end <= overlap_start:
        return 0
    return int((overlap_end - overlap_start).total_seconds())


def build_runtime_stats(db: Session, now: datetime, config: models.SystemConfig):
    first_hour = hour_floor(now) - timedelta(hours=23)
    logs = (
        db.query(models.SystemLog)
        .filter(models.SystemLog.created_at >= first_hour)
        .order_by(models.SystemLog.created_at.asc())
        .all()
    )
    start_events = [log.created_at for log in logs if is_runtime_start_log(log.message)]
    stop_events = [log.created_at for log in logs if is_runtime_stop_log(log.message)]
    token_switch_count = len([log for log in logs if is_token_switch_log(log.message)])
    if config.stable_uptime_started_at:
        start_events.append(config.stable_uptime_started_at)

    events = sorted(
        [(event_at, "up") for event_at in start_events]
        + [(event_at, "down") for event_at in stop_events],
        key=lambda item: item[0],
    )
    is_up = bool(config.stable_uptime_started_at and config.stable_uptime_started_at <= first_hour)
    down_since = None
    downtime_intervals = []
    downtime_count = 0

    for event_at, event_type in events:
        if event_at < first_hour:
            continue
        if event_type == "down":
            if down_since is None:
                down_since = event_at
                downtime_count += 1
            is_up = False
        elif event_type == "up" and not is_up:
            if down_since is not None:
                downtime_intervals.append((down_since, event_at))
            is_up = True
            down_since = None

    if not is_up and down_since is not None:
        downtime_intervals.append((down_since, now))

    hours = []
    for offset in range(24):
        hour_start = first_hour + timedelta(hours=offset)
        hour_end = hour_start + timedelta(hours=1)
        observed_end = min(hour_end, now)
        observed_seconds = max(1, int((observed_end - hour_start).total_seconds()))
        down_seconds = sum(
            overlap_seconds(start, end, hour_start, observed_end)
            for start, end in downtime_intervals
        )
        stops_in_hour = [event for event in stop_events if hour_start <= event < hour_end]
        has_started_by_hour = any(event < observed_end for event in start_events)
        if not has_started_by_hour:
            status_value = "down"
        elif down_seconds >= observed_seconds:
            status_value = "down"
        elif down_seconds > 0:
            status = "interrupted"
            status_value = status
        else:
            status_value = "stable"

        hours.append(
            {
                "hour_start": hour_start,
                "hour_end": hour_end,
                "status": status_value,
                "interruption_count": len(stops_in_hour),
            }
        )

    return {
        "runtime_hours": hours,
        "downtime_count_24h": downtime_count,
        "downtime_seconds_24h": sum(
            overlap_seconds(start, end, first_hour, now)
            for start, end in downtime_intervals
        ),
        "token_switch_count_24h": token_switch_count,
    }


def init_db():
    db = SessionLocal()
    try:
        admin_user = os.getenv("ADMIN_USERNAME", "admin_temp")
        admin_pass = os.getenv("ADMIN_PASSWORD", "pass_temp")

        admin = db.query(models.Admin).filter(models.Admin.username == admin_user).first()
        if not admin:
            db.add(
                models.Admin(
                    username=admin_user,
                    hashed_password=auth.get_password_hash(admin_pass),
                )
            )
        ensure_config(db)
        db.commit()
    finally:
        db.close()


init_db()


async def get_current_admin(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = schemas.TokenData(username=username)
    except jwt.PyJWTError:
        raise credentials_exception

    user = db.query(models.Admin).filter(models.Admin.username == token_data.username).first()
    if user is None:
        raise credentials_exception
    return user


@app.post("/api/login", response_model=schemas.Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.Admin).filter(models.Admin.username == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/api/config", response_model=schemas.SystemConfigBase)
def get_config(db: Session = Depends(get_db), current_admin: models.Admin = Depends(get_current_admin)):
    return ensure_config(db)


@app.put("/api/config", response_model=schemas.SystemConfigBase)
def update_config(
    config_update: schemas.SystemConfigUpdate,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    config = ensure_config(db)
    if config_update.tg_bot_token is not None:
        config.tg_bot_token = config_update.tg_bot_token
    if config_update.tg_chat_id is not None:
        config.tg_chat_id = config_update.tg_chat_id
    updated_fields = config_update.model_fields_set
    if "ai_enabled" in updated_fields:
        config.ai_enabled = config_update.ai_enabled
    primary_ai_updated = bool({"ai_api_key", "ai_base_url", "ai_model"} & updated_fields)
    if "ai_api_key" in updated_fields:
        config.ai_api_key = config_update.ai_api_key
    if "ai_base_url" in updated_fields:
        config.ai_base_url = config_update.ai_base_url or "https://api.deepseek.com"
    if "ai_model" in updated_fields:
        config.ai_model = config_update.ai_model or "deepseek-chat"
    if "ai_backup_api_key" in updated_fields:
        config.ai_backup_api_key = config_update.ai_backup_api_key
    if "ai_backup_base_url" in updated_fields:
        config.ai_backup_base_url = config_update.ai_backup_base_url
    if "ai_backup_model" in updated_fields:
        config.ai_backup_model = config_update.ai_backup_model
    if primary_ai_updated or not (config.ai_backup_api_key and config.ai_backup_base_url and config.ai_backup_model):
        config.ai_active_provider = "primary"
        config.ai_primary_next_check_at = None
    if "ai_forward_format" in updated_fields:
        config.ai_forward_format = config_update.ai_forward_format or "summary_original"
    db.commit()
    db.refresh(config)
    return config


def ai_provider_settings(config: models.SystemConfig, provider: str):
    if provider == "primary":
        return (
            config.ai_api_key,
            config.ai_base_url or "https://api.deepseek.com",
            config.ai_model or "deepseek-chat",
            "Primary AI API",
        )
    if provider == "backup":
        return (
            config.ai_backup_api_key,
            config.ai_backup_base_url,
            config.ai_backup_model,
            "Backup AI API",
        )
    raise HTTPException(status_code=404, detail="AI provider not found")


async def get_ai_balance_for_provider(config: models.SystemConfig, provider: str):
    api_key, base_url, model, provider_name = ai_provider_settings(config, provider)
    is_google = is_google_translate_config(api_key, base_url, model)
    if (not api_key or not base_url) and not is_google:
        raise HTTPException(status_code=400, detail=f"{provider_name} is not configured")

    balance, error = await get_api_balance(
        api_key,
        base_url,
    )
    if error:
        raise HTTPException(status_code=400, detail=error)

    return {
        "is_available": balance.get("is_available"),
        "balance_infos": balance.get("balance_infos") or [],
    }


@app.get("/api/config/ai-balance", response_model=schemas.AIBalanceResponse)
async def get_ai_balance_primary(
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    config = ensure_config(db)
    return await get_ai_balance_for_provider(config, "primary")


@app.get("/api/config/ai-balance/{provider}", response_model=schemas.AIBalanceResponse)
async def get_ai_balance_by_provider(
    provider: str,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    config = ensure_config(db)
    return await get_ai_balance_for_provider(config, provider)


async def test_ai_provider(config: models.SystemConfig, provider: str):
    api_key, base_url, model, provider_name = ai_provider_settings(config, provider)
    if not api_key or not base_url or not model:
        raise HTTPException(status_code=400, detail=f"{provider_name} is not configured")
    sample_message = "We should delay the subnet launch until the validator emissions are stable."
    summary, error, _status_code = await request_chinese_translation(
        api_key,
        base_url,
        model,
        sample_message,
    )
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {"detail": f"{provider_name} test completed successfully", "summary": summary}


@app.post("/api/config/test-ai", response_model=schemas.AITestResponse)
async def test_ai_summary(
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    config = ensure_config(db)
    is_google = is_google_translate_config(config.ai_api_key, config.ai_base_url, config.ai_model)
    if not config.ai_api_key and not is_google:
        raise HTTPException(status_code=400, detail="AI API Key is not configured")

    summary, error, provider, switch_message = await generate_chinese_summary_with_failover(
        config,
        "We should delay the subnet launch until the validator emissions are stable.",
    )
    if error:
        raise HTTPException(status_code=400, detail=error)

    if switch_message:
        db.add(models.SystemLog(level="warning", message=switch_message))
    db.add(models.SystemLog(level="success", message="AI summary test completed successfully."))
    db.commit()
    prune_old_logs(db)
    return {"detail": f"AI summary test completed successfully via {provider}", "summary": summary}


@app.post("/api/config/test-ai/{provider}", response_model=schemas.AITestResponse)
async def test_ai_summary_by_provider(
    provider: str,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    config = ensure_config(db)
    result = await test_ai_provider(config, provider)
    db.add(models.SystemLog(level="success", message=f"{provider} AI summary test completed successfully."))
    db.commit()
    prune_old_logs(db)
    return result


@app.post("/api/config/test-telegram", response_model=schemas.MessageResponse)
async def test_telegram(
    config_update: schemas.SystemConfigUpdate | None = Body(default=None),
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    config = ensure_config(db)
    bot_token = config_update.tg_bot_token if config_update and config_update.tg_bot_token else config.tg_bot_token
    chat_id = config_update.tg_chat_id if config_update and config_update.tg_chat_id else config.tg_chat_id
    if not bot_token or not chat_id:
        raise HTTPException(status_code=400, detail="Telegram Bot Token and Chat ID are required")

    success, error = await send_telegram_message(
        bot_token,
        chat_id,
        "<b>[DC Monitor]</b>\nTelegram test message sent successfully.",
    )
    if not success:
        raise HTTPException(status_code=400, detail=error or "Failed to send test message")

    db.add(models.SystemLog(level="success", message="Telegram test message sent successfully."))
    db.commit()
    prune_old_logs(db)
    return {"detail": "Telegram test message sent successfully"}


@app.get("/api/tokens", response_model=List[schemas.DiscordTokenResponse])
def get_tokens(db: Session = Depends(get_db), current_admin: models.Admin = Depends(get_current_admin)):
    return db.query(models.DiscordToken).order_by(models.DiscordToken.id.asc()).all()


@app.post("/api/tokens", response_model=schemas.DiscordTokenResponse)
async def add_token(
    token_create: schemas.DiscordTokenCreate,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    db_token = models.DiscordToken(token=token_create.token, note=token_create.note, status="standby")
    db.add(db_token)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Token already exists")
    db.refresh(db_token)
    token_id = db_token.id

    checked_token = await run_token_check(token_id, manual=True)
    return checked_token or db_token


@app.post("/api/tokens/{token_id}/check", response_model=schemas.DiscordTokenResponse)
async def check_token(
    token_id: int,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    db_token = db.query(models.DiscordToken).filter(models.DiscordToken.id == token_id).first()
    if not db_token:
        raise HTTPException(status_code=404, detail="Token not found")
    if db_token.status == "online":
        raise HTTPException(status_code=409, detail="Active token is already online")
    if db_token.status == "disabled":
        raise HTTPException(status_code=409, detail="Enable the token before checking it")

    checked_token = await run_token_check(token_id, manual=True)
    if not checked_token:
        raise HTTPException(status_code=404, detail="Token not found")
    return checked_token


@app.post("/api/tokens/{token_id}/check-servers", response_model=schemas.DiscordTokenResponse)
async def check_token_servers(
    token_id: int,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    db_token = db.query(models.DiscordToken).filter(models.DiscordToken.id == token_id).first()
    if not db_token:
        raise HTTPException(status_code=404, detail="Token not found")
    if db_token.status == "disabled":
        raise HTTPException(status_code=409, detail="Enable the token before checking it")

    if db_token.status == "online":
        ok = await monitor_manager.check_online_client_by_id(token_id, full_health=False, reason="manual server coverage")
        refreshed_token = db.query(models.DiscordToken).filter(models.DiscordToken.id == token_id).first()
        if not ok and refreshed_token:
            return refreshed_token
        if refreshed_token and refreshed_token.error_message:
            return refreshed_token
        if refreshed_token:
            refreshed_token.error_message = None
            db.commit()
            db.refresh(refreshed_token)
            return refreshed_token
        raise HTTPException(status_code=404, detail="Token not found")

    checked_token = await run_token_check(token_id, manual=True)
    if not checked_token:
        raise HTTPException(status_code=404, detail="Token not found")
    return checked_token


@app.patch("/api/tokens/{token_id}", response_model=schemas.DiscordTokenResponse)
def update_token(
    token_id: int,
    token_update: schemas.DiscordTokenUpdate,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    db_token = db.query(models.DiscordToken).filter(models.DiscordToken.id == token_id).first()
    if not db_token:
        raise HTTPException(status_code=404, detail="Token not found")

    db_token.note = token_update.note
    db.commit()
    db.refresh(db_token)
    return db_token


@app.patch("/api/tokens/{token_id}/status", response_model=schemas.DiscordTokenResponse)
def update_token_status(
    token_id: int,
    status_update: schemas.TokenStatusUpdate,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    db_token = db.query(models.DiscordToken).filter(models.DiscordToken.id == token_id).first()
    if not db_token:
        raise HTTPException(status_code=404, detail="Token not found")
    if db_token.status == "online" and status_update.status == "disabled":
        raise HTTPException(status_code=409, detail="Stop the system before disabling the active token")

    db_token.status = status_update.status
    db_token.error_message = None
    db_token.next_retry_at = None
    db_token.next_check_at = None
    if status_update.status == "standby":
        db_token.failure_count = 0
    db.commit()
    db.refresh(db_token)
    return db_token


@app.post("/api/tokens/bulk-delete", response_model=schemas.BulkTokenDeleteResponse)
def bulk_delete_tokens(
    payload: schemas.BulkTokenDeleteRequest,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    config = ensure_config(db)
    tokens = db.query(models.DiscordToken).filter(models.DiscordToken.id.in_(payload.ids)).all()
    deleted_ids = []
    skipped_ids = []

    for token in tokens:
        if token.status == "online" or config.active_token_id == token.id:
            skipped_ids.append(token.id)
            continue
        deleted_ids.append(token.id)
        db.delete(token)

    db.commit()
    return {
        "deleted_ids": deleted_ids,
        "skipped_ids": skipped_ids,
        "detail": f"Deleted {len(deleted_ids)} token(s), skipped {len(skipped_ids)} active token(s).",
    }


@app.delete("/api/tokens/{token_id}", response_model=schemas.MessageResponse)
def delete_token(token_id: int, db: Session = Depends(get_db), current_admin: models.Admin = Depends(get_current_admin)):
    db_token = db.query(models.DiscordToken).filter(models.DiscordToken.id == token_id).first()
    if not db_token:
        raise HTTPException(status_code=404, detail="Token not found")
    config = ensure_config(db)
    if db_token.status == "online" or config.active_token_id == token_id:
        raise HTTPException(status_code=409, detail="Stop the system before deleting the active token")
    db.delete(db_token)
    db.commit()
    return {"detail": "Token deleted"}


@app.get("/api/targets/servers", response_model=List[schemas.TargetServerResponse])
def get_target_servers(db: Session = Depends(get_db), current_admin: models.Admin = Depends(get_current_admin)):
    return db.query(models.TargetServer).order_by(models.TargetServer.id.asc()).all()


@app.post("/api/targets/servers", response_model=schemas.TargetServerResponse)
def add_target_server(
    server: schemas.TargetServerCreate,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    db_server = models.TargetServer(guild_id=server.guild_id, name=server.name)
    db.add(db_server)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Server already exists")
    db.refresh(db_server)
    return db_server


@app.patch("/api/targets/servers/{server_id}", response_model=schemas.TargetServerResponse)
def update_target_server(
    server_id: int,
    server_update: schemas.TargetServerUpdate,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    db_server = db.query(models.TargetServer).filter(models.TargetServer.id == server_id).first()
    if not db_server:
        raise HTTPException(status_code=404, detail="Server not found")
    db_server.name = server_update.name
    db.commit()
    db.refresh(db_server)
    return db_server


@app.delete("/api/targets/servers/{server_id}", response_model=schemas.MessageResponse)
def delete_target_server(server_id: int, db: Session = Depends(get_db), current_admin: models.Admin = Depends(get_current_admin)):
    db_server = db.query(models.TargetServer).filter(models.TargetServer.id == server_id).first()
    if not db_server:
        raise HTTPException(status_code=404, detail="Server not found")
    db.delete(db_server)
    db.commit()
    return {"detail": "Server removed"}


@app.post("/api/targets/servers/bulk-delete", response_model=schemas.BulkTargetDeleteResponse)
def bulk_delete_target_servers(
    payload: schemas.BulkTargetDeleteRequest,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    targets = db.query(models.TargetServer).filter(models.TargetServer.id.in_(payload.ids)).all()
    deleted_ids = [target.id for target in targets]
    for target in targets:
        db.delete(target)
    db.commit()
    return {"deleted_ids": deleted_ids, "detail": f"Deleted {len(deleted_ids)} server target(s)."}


@app.get("/api/targets/users", response_model=List[schemas.TargetUserResponse])
def get_target_users(db: Session = Depends(get_db), current_admin: models.Admin = Depends(get_current_admin)):
    return db.query(models.TargetUser).order_by(models.TargetUser.id.asc()).all()


@app.post("/api/targets/users", response_model=schemas.TargetUserResponse)
def add_target_user(
    user: schemas.TargetUserCreate,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    existing_username = db.query(models.TargetUser).filter(models.TargetUser.username == user.username).first()
    if existing_username:
        raise HTTPException(status_code=409, detail="Username already exists")
    if user.user_id:
        existing_user_id = db.query(models.TargetUser).filter(models.TargetUser.user_id == user.user_id).first()
        if existing_user_id:
            raise HTTPException(status_code=409, detail="User ID already exists")

    db_user = models.TargetUser(
        user_id=user.user_id,
        username=user.username,
        note=user.note,
        highlight_enabled=user.highlight_enabled,
    )
    db.add(db_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="User already exists")
    db.refresh(db_user)
    return db_user


@app.patch("/api/targets/users/{user_id}", response_model=schemas.TargetUserResponse)
def update_target_user(
    user_id: int,
    user_update: schemas.TargetUserUpdate,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    db_user = db.query(models.TargetUser).filter(models.TargetUser.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    updates = user_update.model_dump(exclude_unset=True)
    if "note" in updates:
        db_user.note = updates["note"]
    if "highlight_enabled" in updates:
        db_user.highlight_enabled = updates["highlight_enabled"]
    db.commit()
    db.refresh(db_user)
    return db_user


@app.delete("/api/targets/users/{user_id}", response_model=schemas.MessageResponse)
def delete_target_user(user_id: int, db: Session = Depends(get_db), current_admin: models.Admin = Depends(get_current_admin)):
    db_user = db.query(models.TargetUser).filter(models.TargetUser.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(db_user)
    db.commit()
    return {"detail": "User removed"}


@app.post("/api/targets/users/bulk-delete", response_model=schemas.BulkTargetDeleteResponse)
def bulk_delete_target_users(
    payload: schemas.BulkTargetDeleteRequest,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    targets = db.query(models.TargetUser).filter(models.TargetUser.id.in_(payload.ids)).all()
    deleted_ids = [target.id for target in targets]
    for target in targets:
        db.delete(target)
    db.commit()
    return {"deleted_ids": deleted_ids, "detail": f"Deleted {len(deleted_ids)} user target(s)."}


@app.get("/api/targets/channels", response_model=List[schemas.TargetChannelResponse])
def get_target_channels(db: Session = Depends(get_db), current_admin: models.Admin = Depends(get_current_admin)):
    return db.query(models.TargetChannel).order_by(models.TargetChannel.id.asc()).all()


@app.post("/api/targets/channels", response_model=schemas.TargetChannelResponse)
def add_target_channel(
    channel: schemas.TargetChannelCreate,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    db_channel = models.TargetChannel(channel_id=channel.channel_id, note=channel.note)
    db.add(db_channel)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Channel already exists")
    db.refresh(db_channel)
    return db_channel


@app.patch("/api/targets/channels/{channel_id}", response_model=schemas.TargetChannelResponse)
def update_target_channel(
    channel_id: int,
    channel_update: schemas.TargetChannelUpdate,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    db_channel = db.query(models.TargetChannel).filter(models.TargetChannel.id == channel_id).first()
    if not db_channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    db_channel.note = channel_update.note
    db.commit()
    db.refresh(db_channel)
    return db_channel


@app.delete("/api/targets/channels/{channel_id}", response_model=schemas.MessageResponse)
def delete_target_channel(channel_id: int, db: Session = Depends(get_db), current_admin: models.Admin = Depends(get_current_admin)):
    db_channel = db.query(models.TargetChannel).filter(models.TargetChannel.id == channel_id).first()
    if not db_channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    db.delete(db_channel)
    db.commit()
    return {"detail": "Channel removed"}


@app.post("/api/targets/channels/bulk-delete", response_model=schemas.BulkTargetDeleteResponse)
def bulk_delete_target_channels(
    payload: schemas.BulkTargetDeleteRequest,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_admin),
):
    targets = db.query(models.TargetChannel).filter(models.TargetChannel.id.in_(payload.ids)).all()
    deleted_ids = [target.id for target in targets]
    for target in targets:
        db.delete(target)
    db.commit()
    return {"deleted_ids": deleted_ids, "detail": f"Deleted {len(deleted_ids)} channel target(s)."}


@app.get("/api/logs", response_model=List[schemas.SystemLogResponse])
def get_logs(limit: int = 100, db: Session = Depends(get_db), current_admin: models.Admin = Depends(get_current_admin)):
    prune_old_logs(db)
    limit = min(max(limit, 1), 1000)
    return db.query(models.SystemLog).order_by(models.SystemLog.created_at.desc()).limit(limit).all()


@app.on_event("startup")
async def startup_event():
    db = SessionLocal()
    try:
        config = ensure_config(db)
        db.query(models.DiscordToken).filter(models.DiscordToken.status == "online").update({"status": "offline"})
        config.active_token_id = None
        config.stable_uptime_started_at = None
        config.last_heartbeat_at = datetime.utcnow()
        if config.is_running:
            db.add(models.SystemLog(level="warning", message="System monitoring interrupted by backend restart."))
        db.commit()
        prune_old_logs(db)
        if config.is_running:
            await monitor_manager.start()
        await token_health_manager.start()
    finally:
        db.close()


@app.post("/api/system/start", response_model=schemas.MessageResponse)
async def start_system(db: Session = Depends(get_db), current_admin: models.Admin = Depends(get_current_admin)):
    available_count = db.query(models.DiscordToken).filter(models.DiscordToken.status.in_(["standby", "offline", "rate_limited"])).count()
    if available_count == 0:
        raise HTTPException(status_code=400, detail="No available Discord tokens")
    await monitor_manager.start()
    return {"detail": "System started"}


@app.post("/api/system/stop", response_model=schemas.MessageResponse)
async def stop_system(db: Session = Depends(get_db), current_admin: models.Admin = Depends(get_current_admin)):
    await monitor_manager.stop()
    return {"detail": "System stopped"}


@app.get("/api/system/status", response_model=schemas.SystemStatusResponse)
async def get_system_status(db: Session = Depends(get_db), current_admin: models.Admin = Depends(get_current_admin)):
    config = ensure_config(db)
    tokens = db.query(models.DiscordToken).all()
    now = datetime.utcnow()
    active_token = None
    if config.active_token_id:
        active_token = db.query(models.DiscordToken).filter(models.DiscordToken.id == config.active_token_id).first()
    stable_uptime_seconds = 0
    if config.stable_uptime_started_at and config.is_running and active_token and active_token.status == "online":
        stable_uptime_seconds = max(0, int((now - config.stable_uptime_started_at).total_seconds()))
    runtime_stats = build_runtime_stats(db, now, config)

    return {
        "is_running": bool(config.is_running),
        "worker_running": monitor_manager.is_worker_running(),
        "active_token_id": config.active_token_id,
        "active_token_status": active_token.status if active_token else None,
        "last_started_at": config.last_started_at,
        "last_stopped_at": config.last_stopped_at,
        "last_heartbeat_at": config.last_heartbeat_at,
        "last_forwarded_at": config.last_forwarded_at,
        "last_error": config.last_error,
        "stable_uptime_started_at": config.stable_uptime_started_at,
        "stable_uptime_seconds": stable_uptime_seconds,
        "runtime_hours": runtime_stats["runtime_hours"],
        "downtime_count_24h": runtime_stats["downtime_count_24h"],
        "downtime_seconds_24h": runtime_stats["downtime_seconds_24h"],
        "token_switch_count_24h": runtime_stats["token_switch_count_24h"],
        "token_total": len(tokens),
        "token_online": len([token for token in tokens if token.status == "online"]),
        "token_available": len([token for token in tokens if token.status in {"standby", "offline"}]),
        "token_disabled": len([token for token in tokens if token.status == "disabled"]),
        "token_invalid": len([token for token in tokens if token.status == "invalid"]),
        "token_retrying": len([
            token
            for token in tokens
            if token.next_retry_at is not None and token.next_retry_at > now
        ]),
        "token_health_worker_running": token_health_manager.is_worker_running(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
