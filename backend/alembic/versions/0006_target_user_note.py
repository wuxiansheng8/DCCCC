from alembic import op
import sqlalchemy as sa

revision = "0006_target_user_note"
down_revision = "0005_username_targets"
branch_labels = None
depends_on = None


def column_names(bind, table):
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    if "note" not in column_names(bind, "target_users"):
        op.add_column("target_users", sa.Column("note", sa.String(length=100), nullable=True))


def downgrade():
    bind = op.get_bind()
    if "note" in column_names(bind, "target_users"):
        op.drop_column("target_users", "note")
