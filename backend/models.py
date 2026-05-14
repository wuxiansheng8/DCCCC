from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)


class SystemConfig(Base):
    __tablename__ = "system_configs"

    id = Column(Integer, primary_key=True, index=True)
    tg_bot_token = Column(String(255), nullable=True)
    tg_chat_id = Column(String(100), nullable=True)
    ai_enabled = Column(Boolean, default=False, nullable=False)
    ai_api_key = Column(String(255), nullable=True)
    ai_base_url = Column(String(255), default="https://api.deepseek.com", nullable=False)
    ai_model = Column(String(100), default="deepseek-chat", nullable=False)
    ai_backup_api_key = Column(String(255), nullable=True)
    ai_backup_base_url = Column(String(255), nullable=True)
    ai_backup_model = Column(String(100), nullable=True)
    ai_active_provider = Column(String(20), default="primary", nullable=False)
    ai_primary_next_check_at = Column(DateTime, nullable=True)
    ai_forward_format = Column(String(30), default="summary_original", nullable=False)
    is_running = Column(Boolean, default=False, nullable=False)
    active_token_id = Column(Integer, nullable=True)
    last_started_at = Column(DateTime, nullable=True)
    last_stopped_at = Column(DateTime, nullable=True)
    last_heartbeat_at = Column(DateTime, nullable=True)
    last_forwarded_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    stable_uptime_started_at = Column(DateTime, nullable=True)


class DiscordToken(Base):
    __tablename__ = "discord_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(255), unique=True, index=True, nullable=False)
    note = Column(String(100), nullable=True)
    # Status: standby, online, offline, invalid, rate_limited, disabled
    status = Column(String(20), default="standby", index=True, nullable=False)
    last_used = Column(DateTime, nullable=True)
    next_retry_at = Column(DateTime, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    next_check_at = Column(DateTime, nullable=True)
    failure_count = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class TargetServer(Base):
    __tablename__ = "target_servers"

    id = Column(Integer, primary_key=True, index=True)
    guild_id = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=True)


class TargetUser(Base):
    __tablename__ = "target_users"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(50), unique=True, index=True, nullable=True)
    username = Column(String(100), index=True, nullable=True)
    note = Column(String(100), nullable=True)
    highlight_enabled = Column(Boolean, default=False, nullable=False)


class TargetChannel(Base):
    __tablename__ = "target_channels"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(String(50), unique=True, index=True, nullable=False)
    note = Column(String(100), nullable=True)


class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)
    # Level: info, success, error, warning
    level = Column(String(20), default="info", index=True, nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)


class ForwardedMessage(Base):
    __tablename__ = "forwarded_messages"

    id = Column(Integer, primary_key=True, index=True)
    guild_id = Column(String(50), index=True, nullable=False)
    channel_id = Column(String(50), index=True, nullable=False)
    message_id = Column(String(100), unique=True, index=True, nullable=False)
    status = Column(String(20), default="sending", index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    sent_at = Column(DateTime, nullable=True)
