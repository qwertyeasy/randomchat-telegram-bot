"""Репозиторий матрицы совместимости M (Фаза 6)."""
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CompatibilityMatrix

_DIMS = 12
_IDENTITY = [1.0 if i == j else 0.0 for i in range(_DIMS) for j in range(_DIMS)]


class MatrixRepository:
    SINGLETON_ID = 1

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self) -> CompatibilityMatrix:
        """Вернуть матрицу (единственная строка). Создать identity если её нет."""
        obj = await self.session.get(CompatibilityMatrix, self.SINGLETON_ID)
        if obj is None:
            obj = CompatibilityMatrix(
                id=self.SINGLETON_ID,
                matrix=list(_IDENTITY),
                sample_count=0,
                updated_at=datetime.utcnow(),
            )
            self.session.add(obj)
        return obj

    async def save(self, matrix: list[float], sample_count: int) -> None:
        obj = await self.get()
        obj.matrix = matrix
        obj.sample_count = sample_count
        obj.updated_at = datetime.utcnow()
