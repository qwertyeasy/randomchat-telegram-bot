"""hnsw index on personality_vector"""

from alembic import op


revision = "0003_hnsw_index"
down_revision = "0002_user_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # HNSW — приближённый поиск ближайших соседей, O(log N) вместо O(N).
    # vector_cosine_ops — оператор косинусного расстояния (<=>).
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_user_profiles_vector_hnsw
        ON user_profiles
        USING hnsw (personality_vector vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_user_profiles_vector_hnsw")
