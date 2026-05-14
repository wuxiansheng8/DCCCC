from alembic import op
import sqlalchemy as sa

revision = "0002_add_token_note"
down_revision = "0001_state_lifecycle_logs"
branch_labels = None
depends_on = None


def column_names(bind, table):
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    if "note" not in column_names(bind, "discord_tokens"):
        op.add_column("discord_tokens", sa.Column("note", sa.String(length=100), nullable=True))


def downgrade():
    bind = op.get_bind()
    if "note" in column_names(bind, "discord_tokens"):
        op.drop_column("discord_tokens", "note")
