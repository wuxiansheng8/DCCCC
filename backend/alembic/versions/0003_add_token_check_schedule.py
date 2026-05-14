from alembic import op
import sqlalchemy as sa

revision = "0003_add_token_check_schedule"
down_revision = "0002_add_token_note"
branch_labels = None
depends_on = None


def column_names(bind, table):
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    columns = column_names(bind, "discord_tokens")
    if "last_checked_at" not in columns:
        op.add_column("discord_tokens", sa.Column("last_checked_at", sa.DateTime(), nullable=True))
    if "next_check_at" not in columns:
        op.add_column("discord_tokens", sa.Column("next_check_at", sa.DateTime(), nullable=True))


def downgrade():
    bind = op.get_bind()
    columns = column_names(bind, "discord_tokens")
    if "next_check_at" in columns:
        op.drop_column("discord_tokens", "next_check_at")
    if "last_checked_at" in columns:
        op.drop_column("discord_tokens", "last_checked_at")
