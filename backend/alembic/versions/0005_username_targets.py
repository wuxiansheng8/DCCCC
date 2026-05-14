from alembic import op
import sqlalchemy as sa

revision = "0005_username_targets"
down_revision = "0004_forwarded_messages"
branch_labels = None
depends_on = None


def column_names(bind, table):
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def column_nullable(bind, table, column):
    for item in sa.inspect(bind).get_columns(table):
        if item["name"] == column:
            return item.get("nullable")
    return None


def index_names(bind, table):
    return {index["name"] for index in sa.inspect(bind).get_indexes(table)}


def upgrade():
    bind = op.get_bind()
    columns = column_names(bind, "target_users")

    if "user_id" in columns and column_nullable(bind, "target_users", "user_id") is False:
        with op.batch_alter_table("target_users") as batch:
            batch.alter_column("user_id", existing_type=sa.String(length=50), nullable=True)

    if "username" not in columns:
        op.add_column("target_users", sa.Column("username", sa.String(length=100), nullable=True))

    if "ix_target_users_username" not in index_names(bind, "target_users"):
        op.create_index("ix_target_users_username", "target_users", ["username"])


def downgrade():
    bind = op.get_bind()
    if "ix_target_users_username" in index_names(bind, "target_users"):
        op.drop_index("ix_target_users_username", table_name="target_users")
