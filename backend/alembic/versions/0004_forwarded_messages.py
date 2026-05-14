from alembic import op
import sqlalchemy as sa

revision = "0004_forwarded_messages"
down_revision = "0003_add_token_check_schedule"
branch_labels = None
depends_on = None


def table_names(bind):
    return set(sa.inspect(bind).get_table_names())


def index_names(bind, table):
    return {index["name"] for index in sa.inspect(bind).get_indexes(table)}


def create_index_if_missing(bind, name, table, columns, unique=False):
    if name not in index_names(bind, table):
        op.create_index(name, table, columns, unique=unique)


def upgrade():
    bind = op.get_bind()
    if "forwarded_messages" not in table_names(bind):
        op.create_table(
            "forwarded_messages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("guild_id", sa.String(length=50), nullable=False),
            sa.Column("channel_id", sa.String(length=50), nullable=False),
            sa.Column("message_id", sa.String(length=100), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="sending"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
        )

    create_index_if_missing(bind, "ix_forwarded_messages_guild_id", "forwarded_messages", ["guild_id"])
    create_index_if_missing(bind, "ix_forwarded_messages_channel_id", "forwarded_messages", ["channel_id"])
    create_index_if_missing(bind, "ix_forwarded_messages_message_id", "forwarded_messages", ["message_id"], unique=True)
    create_index_if_missing(bind, "ix_forwarded_messages_status", "forwarded_messages", ["status"])
    create_index_if_missing(bind, "ix_forwarded_messages_created_at", "forwarded_messages", ["created_at"])


def downgrade():
    bind = op.get_bind()
    if "forwarded_messages" in table_names(bind):
        indexes = index_names(bind, "forwarded_messages")
        for index_name in (
            "ix_forwarded_messages_created_at",
            "ix_forwarded_messages_status",
            "ix_forwarded_messages_message_id",
            "ix_forwarded_messages_channel_id",
            "ix_forwarded_messages_guild_id",
        ):
            if index_name in indexes:
                op.drop_index(index_name, table_name="forwarded_messages")
        op.drop_table("forwarded_messages")
