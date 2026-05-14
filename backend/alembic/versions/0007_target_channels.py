from alembic import op
import sqlalchemy as sa

revision = "0007_target_channels"
down_revision = "0006_target_user_note"
branch_labels = None
depends_on = None


def table_names(bind):
    return set(sa.inspect(bind).get_table_names())


def upgrade():
    bind = op.get_bind()
    if "target_channels" not in table_names(bind):
        op.create_table(
            "target_channels",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("channel_id", sa.String(length=50), nullable=False),
            sa.Column("note", sa.String(length=100), nullable=True),
        )
        op.create_index("ix_target_channels_id", "target_channels", ["id"])
        op.create_index("ix_target_channels_channel_id", "target_channels", ["channel_id"], unique=True)


def downgrade():
    bind = op.get_bind()
    if "target_channels" in table_names(bind):
        op.drop_table("target_channels")
