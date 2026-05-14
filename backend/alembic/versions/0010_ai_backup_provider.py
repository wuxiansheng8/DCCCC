from alembic import op
import sqlalchemy as sa

revision = "0010_ai_backup_provider"
down_revision = "0009_stable_uptime"
branch_labels = None
depends_on = None


def column_names(bind, table):
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def add_column_if_missing(bind, table, column):
    if column.name not in column_names(bind, table):
        op.add_column(table, column)


def upgrade():
    bind = op.get_bind()
    add_column_if_missing(bind, "system_configs", sa.Column("ai_backup_api_key", sa.String(length=255), nullable=True))
    add_column_if_missing(bind, "system_configs", sa.Column("ai_backup_base_url", sa.String(length=255), nullable=True))
    add_column_if_missing(bind, "system_configs", sa.Column("ai_backup_model", sa.String(length=100), nullable=True))
    add_column_if_missing(
        bind,
        "system_configs",
        sa.Column("ai_active_provider", sa.String(length=20), nullable=False, server_default="primary"),
    )
    add_column_if_missing(bind, "system_configs", sa.Column("ai_primary_next_check_at", sa.DateTime(), nullable=True))


def downgrade():
    bind = op.get_bind()
    columns = column_names(bind, "system_configs")
    for column_name in [
        "ai_primary_next_check_at",
        "ai_active_provider",
        "ai_backup_model",
        "ai_backup_base_url",
        "ai_backup_api_key",
    ]:
        if column_name in columns:
            op.drop_column("system_configs", column_name)
