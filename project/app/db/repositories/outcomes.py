"""Репозиторий исходов сессий (Фаза 6)."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SessionOutcome


class OutcomeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, outcome: SessionOutcome) -> SessionOutcome:
        self.session.add(outcome)
        return outcome
