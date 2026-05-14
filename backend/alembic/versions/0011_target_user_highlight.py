from alembic import op
import sqlalchemy as sa

revision = "0011_target_user_highlight"
down_revision = "0010_ai_backup_provider"
branch_labels = None
depends_on = None


def column_names(bind, table):
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    if "highlight_enabled" not in column_names(bind, "target_users"):
        op.add_column(
            "target_users",
            sa.Column("highlight_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade():
    bind = op.get_bind()
    if "highlight_enabled" in column_names(bind, "target_users"):
        op.drop_column("target_users", "highlight_enabled")
