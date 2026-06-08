"""user profiles"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "0002_user_profiles"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column(
        "users",
        sa.Column("msg_count", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "user_profiles",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.user_id"),
            primary_key=True,
        ),
        sa.Column("personality_vector", Vector(12), nullable=False),
        sa.Column("interest_tags", sa.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("mbti_scores", sa.ARRAY(sa.Float()), nullable=True),
        sa.Column("msg_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("user_profiles")
    op.drop_column("users", "msg_count")
