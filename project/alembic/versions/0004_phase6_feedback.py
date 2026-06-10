"""Phase 6: session_outcomes + compatibility_matrix"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import Float
from sqlalchemy.dialects.postgresql import ARRAY


revision = "0004_phase6_feedback"
down_revision = "0003_hnsw_index"
branch_labels = None
depends_on = None

_DIMS = 12
# Литерал единичной матрицы 12×12 (построчно) — без bind-параметров,
# чтобы не зависеть от вывода типа массива в asyncpg.
_IDENTITY_SQL = "ARRAY[" + ",".join(
    "1" if i == j else "0" for i in range(_DIMS) for j in range(_DIMS)
) + "]::double precision[]"


def upgrade() -> None:
    op.create_table(
        "session_outcomes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Uuid, nullable=False, index=True),
        sa.Column("user1_id", sa.BigInteger, nullable=False),
        sa.Column("user2_id", sa.BigInteger, nullable=False),
        sa.Column("msg_count_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duration_sec", sa.Integer, nullable=False, server_default="0"),
        sa.Column("contact_shared", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("early_exit", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("success_score", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "compatibility_matrix",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("matrix", ARRAY(Float), nullable=False),
        sa.Column("sample_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.text("now()")),
    )

    # Инициализировать единичной матрицей (стартовое поведение матчинга = cosine).
    op.execute(
        "INSERT INTO compatibility_matrix (id, matrix, sample_count, updated_at) "
        f"VALUES (1, {_IDENTITY_SQL}, 0, now())"
    )


def downgrade() -> None:
    op.drop_table("session_outcomes")
    op.drop_table("compatibility_matrix")
