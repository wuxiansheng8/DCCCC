from alembic import op
import sqlalchemy as sa

revision = "0009_stable_uptime"
down_revision = "0008_ai_summary_config"
branch_labels = None
depends_on = None


def column_names(bind, table):
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    if "stable_uptime_started_at" not in column_names(bind, "system_configs"):
        op.add_column("system_configs", sa.Column("stable_uptime_started_at", sa.DateTime(), nullable=True))


def downgrade():
    bind = op.get_bind()
    if "stable_uptime_started_at" in column_names(bind, "system_configs"):
        op.drop_column("system_configs", "stable_uptime_started_at")
