from alembic import op
import sqlalchemy as sa

revision = "0001_state_lifecycle_logs"
down_revision = None
branch_labels = None
depends_on = None


def table_names(bind):
    return set(sa.inspect(bind).get_table_names())


def column_names(bind, table):
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def index_names(bind, table):
    return {index["name"] for index in sa.inspect(bind).get_indexes(table)}


def add_column_if_missing(bind, table, column):
    if column.name not in column_names(bind, table):
        op.add_column(table, column)


def upgrade():
    bind = op.get_bind()
    tables = table_names(bind)

    if "admins" not in tables:
        op.create_table(
            "admins",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("username", sa.String(length=50), nullable=False),
            sa.Column("hashed_password", sa.String(length=255), nullable=False),
        )
        op.create_index("ix_admins_username", "admins", ["username"], unique=True)

    if "system_configs" not in tables:
        op.create_table(
            "system_configs",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("tg_bot_token", sa.String(length=255), nullable=True),
            sa.Column("tg_chat_id", sa.String(length=100), nullable=True),
            sa.Column("is_running", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("active_token_id", sa.Integer(), nullable=True),
            sa.Column("last_started_at", sa.DateTime(), nullable=True),
            sa.Column("last_stopped_at", sa.DateTime(), nullable=True),
            sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
            sa.Column("last_forwarded_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
        )

    if "discord_tokens" not in tables:
        op.create_table(
            "discord_tokens",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("token", sa.String(length=255), nullable=False),
            sa.Column("note", sa.String(length=100), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="standby"),
            sa.Column("last_used", sa.DateTime(), nullable=True),
            sa.Column("next_retry_at", sa.DateTime(), nullable=True),
            sa.Column("last_checked_at", sa.DateTime(), nullable=True),
            sa.Column("next_check_at", sa.DateTime(), nullable=True),
            sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_discord_tokens_token", "discord_tokens", ["token"], unique=True)
        op.create_index("ix_discord_tokens_status", "discord_tokens", ["status"])

    if "target_servers" not in tables:
        op.create_table(
            "target_servers",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("guild_id", sa.String(length=50), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=True),
        )
        op.create_index("ix_target_servers_guild_id", "target_servers", ["guild_id"], unique=True)

    if "target_users" not in tables:
        op.create_table(
            "target_users",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("user_id", sa.String(length=50), nullable=False),
            sa.Column("username", sa.String(length=100), nullable=True),
        )
        op.create_index("ix_target_users_user_id", "target_users", ["user_id"], unique=True)

    if "system_logs" not in tables:
        op.create_table(
            "system_logs",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("level", sa.String(length=20), nullable=False, server_default="info"),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_system_logs_level", "system_logs", ["level"])
        op.create_index("ix_system_logs_created_at", "system_logs", ["created_at"])

    tables = table_names(bind)
    if "system_configs" in tables:
        add_column_if_missing(bind, "system_configs", sa.Column("active_token_id", sa.Integer(), nullable=True))
        add_column_if_missing(bind, "system_configs", sa.Column("last_started_at", sa.DateTime(), nullable=True))
        add_column_if_missing(bind, "system_configs", sa.Column("last_stopped_at", sa.DateTime(), nullable=True))
        add_column_if_missing(bind, "system_configs", sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True))
        add_column_if_missing(bind, "system_configs", sa.Column("last_forwarded_at", sa.DateTime(), nullable=True))
        add_column_if_missing(bind, "system_configs", sa.Column("last_error", sa.Text(), nullable=True))

    if "discord_tokens" in tables:
        add_column_if_missing(bind, "discord_tokens", sa.Column("note", sa.String(length=100), nullable=True))
        add_column_if_missing(bind, "discord_tokens", sa.Column("next_retry_at", sa.DateTime(), nullable=True))
        add_column_if_missing(bind, "discord_tokens", sa.Column("last_checked_at", sa.DateTime(), nullable=True))
        add_column_if_missing(bind, "discord_tokens", sa.Column("next_check_at", sa.DateTime(), nullable=True))
        add_column_if_missing(bind, "discord_tokens", sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"))
        if "ix_discord_tokens_status" not in index_names(bind, "discord_tokens"):
            op.create_index("ix_discord_tokens_status", "discord_tokens", ["status"])

    if "system_logs" in tables:
        if "ix_system_logs_level" not in index_names(bind, "system_logs"):
            op.create_index("ix_system_logs_level", "system_logs", ["level"])
        if "ix_system_logs_created_at" not in index_names(bind, "system_logs"):
            op.create_index("ix_system_logs_created_at", "system_logs", ["created_at"])


def downgrade():
    pass
