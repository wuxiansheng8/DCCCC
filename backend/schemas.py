from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

TOKEN_STATUSES = {"standby", "online", "offline", "invalid", "rate_limited", "disabled"}
MANUAL_TOKEN_STATUSES = {"standby", "disabled"}
AI_FORWARD_FORMATS = {"original", "summary_original", "summary_only"}


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class SystemConfigBase(BaseModel):
    tg_bot_token: Optional[str] = None
    tg_chat_id: Optional[str] = None
    ai_enabled: bool = False
    ai_api_key: Optional[str] = None
    ai_base_url: str = "https://api.deepseek.com"
    ai_model: str = "deepseek-chat"
    ai_backup_api_key: Optional[str] = None
    ai_backup_base_url: Optional[str] = None
    ai_backup_model: Optional[str] = None
    ai_active_provider: str = "primary"
    ai_primary_next_check_at: Optional[datetime] = None
    ai_forward_format: str = "summary_original"
    is_running: Optional[bool] = False
    active_token_id: Optional[int] = None
    last_started_at: Optional[datetime] = None
    last_stopped_at: Optional[datetime] = None
    last_heartbeat_at: Optional[datetime] = None
    last_forwarded_at: Optional[datetime] = None
    last_error: Optional[str] = None
    stable_uptime_started_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SystemConfigUpdate(BaseModel):
    tg_bot_token: Optional[str] = None
    tg_chat_id: Optional[str] = None
    ai_enabled: Optional[bool] = None
    ai_api_key: Optional[str] = None
    ai_base_url: Optional[str] = None
    ai_model: Optional[str] = None
    ai_backup_api_key: Optional[str] = None
    ai_backup_base_url: Optional[str] = None
    ai_backup_model: Optional[str] = None
    ai_forward_format: Optional[str] = None

    @field_validator(
        "tg_bot_token",
        "tg_chat_id",
        "ai_api_key",
        "ai_base_url",
        "ai_model",
        "ai_backup_api_key",
        "ai_backup_base_url",
        "ai_backup_model",
    )
    @classmethod
    def strip_optional(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        return value or None

    @field_validator("ai_forward_format")
    @classmethod
    def validate_ai_forward_format(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if value not in AI_FORWARD_FORMATS:
            raise ValueError("Invalid AI forward format")
        return value


class DiscordTokenCreate(BaseModel):
    token: str = Field(min_length=20)
    note: Optional[str] = Field(default=None, max_length=100)

    @field_validator("token")
    @classmethod
    def normalize_token(cls, value: str) -> str:
        value = value.strip()
        if " " in value:
            raise ValueError("Token cannot contain spaces")
        return value

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        return value or None


class DiscordTokenUpdate(BaseModel):
    note: Optional[str] = Field(default=None, max_length=100)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        return value or None


class DiscordTokenResponse(BaseModel):
    id: int
    token: str
    note: Optional[str] = None
    status: str
    last_used: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None
    next_check_at: Optional[datetime] = None
    failure_count: int = 0
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TokenStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in MANUAL_TOKEN_STATUSES:
            raise ValueError("Status can only be changed to standby or disabled")
        return value


class BulkTokenDeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1)


class BulkTokenDeleteResponse(BaseModel):
    deleted_ids: list[int]
    skipped_ids: list[int]
    detail: str


class BulkTargetDeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1)


class BulkTargetDeleteResponse(BaseModel):
    deleted_ids: list[int]
    detail: str


class TargetServerCreate(BaseModel):
    guild_id: str = Field(min_length=10, max_length=30)
    name: Optional[str] = None

    @field_validator("guild_id")
    @classmethod
    def validate_guild_id(cls, value: str) -> str:
        value = value.strip()
        if not value.isdigit():
            raise ValueError("Guild ID must be numeric")
        return value

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        return value or None


class TargetServerResponse(TargetServerCreate):
    id: int

    class Config:
        from_attributes = True


class TargetServerUpdate(BaseModel):
    name: Optional[str] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        return value or None


class TargetUserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=100)
    user_id: Optional[str] = Field(default=None, min_length=10, max_length=30)
    note: Optional[str] = Field(default=None, max_length=100)
    highlight_enabled: bool = False

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.strip()
        if any(char.isspace() for char in value):
            raise ValueError("Username cannot contain spaces")
        return value.lower()

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        if not value:
            return None
        if not value.isdigit():
            raise ValueError("User ID must be numeric")
        return value

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        return value or None


class TargetUserUpdate(BaseModel):
    note: Optional[str] = Field(default=None, max_length=100)
    highlight_enabled: Optional[bool] = None

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        return value or None


class TargetUserResponse(BaseModel):
    id: int
    username: Optional[str] = None
    user_id: Optional[str] = None
    note: Optional[str] = None
    highlight_enabled: bool = False

    class Config:
        from_attributes = True


class TargetChannelCreate(BaseModel):
    channel_id: str = Field(min_length=10, max_length=30)
    note: Optional[str] = Field(default=None, max_length=100)

    @field_validator("channel_id")
    @classmethod
    def validate_channel_id(cls, value: str) -> str:
        value = value.strip()
        if not value.isdigit():
            raise ValueError("Channel ID must be numeric")
        return value

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        return value or None


class TargetChannelUpdate(BaseModel):
    note: Optional[str] = Field(default=None, max_length=100)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        return value or None


class TargetChannelResponse(BaseModel):
    id: int
    channel_id: Optional[str] = None
    note: Optional[str] = None

    class Config:
        from_attributes = True


class SystemLogResponse(BaseModel):
    id: int
    level: str
    message: str
    created_at: datetime

    class Config:
        from_attributes = True


class RuntimeHourResponse(BaseModel):
    hour_start: datetime
    hour_end: datetime
    status: str
    interruption_count: int = 0


class SystemStatusResponse(BaseModel):
    is_running: bool
    worker_running: bool
    active_token_id: Optional[int] = None
    active_token_status: Optional[str] = None
    last_started_at: Optional[datetime] = None
    last_stopped_at: Optional[datetime] = None
    last_heartbeat_at: Optional[datetime] = None
    last_forwarded_at: Optional[datetime] = None
    last_error: Optional[str] = None
    stable_uptime_started_at: Optional[datetime] = None
    stable_uptime_seconds: int = 0
    runtime_hours: list["RuntimeHourResponse"] = Field(default_factory=list)
    downtime_count_24h: int = 0
    downtime_seconds_24h: int = 0
    token_switch_count_24h: int = 0
    token_total: int
    token_online: int
    token_available: int
    token_disabled: int
    token_invalid: int
    token_retrying: int
    token_health_worker_running: bool = False


class MessageResponse(BaseModel):
    detail: str


class AIBalanceResponse(BaseModel):
    is_available: Optional[bool] = None
    balance_infos: list[dict] = []


class AITestResponse(BaseModel):
    detail: str
    summary: str
