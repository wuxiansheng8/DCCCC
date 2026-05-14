from alembic import op
import sqlalchemy as sa

revision = "0008_ai_summary_config"
down_revision = "0007_target_channels"
branch_labels = None
depends_on = None


def column_names(bind, table):
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def add_column_if_missing(bind, table, column):
    if column.name not in column_names(bind, table):
        op.add_column(table, column)


def upgrade():
    bind = op.get_bind()
    columns = column_names(bind, "system_configs")
    if "ai_enabled" not in columns:
        op.add_column(
            "system_configs",
            sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    add_column_if_missing(bind, "system_configs", sa.Column("ai_api_key", sa.String(length=255), nullable=True))
    if "ai_base_url" not in columns:
        op.add_column(
            "system_configs",
            sa.Column("ai_base_url", sa.String(length=255), nullable=False, server_default="https://api.deepseek.com"),
        )
    if "ai_model" not in columns:
        op.add_column(
            "system_configs",
            sa.Column("ai_model", sa.String(length=100), nullable=False, server_default="deepseek-chat"),
        )
    if "ai_forward_format" not in columns:
        op.add_column(
            "system_configs",
            sa.Column("ai_forward_format", sa.String(length=30), nullable=False, server_default="summary_original"),
        )


def downgrade():
    bind = op.get_bind()
    columns = column_names(bind, "system_configs")
    for column_name in ["ai_forward_format", "ai_model", "ai_base_url", "ai_api_key", "ai_enabled"]:
        if column_name in columns:
            op.drop_column("system_configs", column_name)
