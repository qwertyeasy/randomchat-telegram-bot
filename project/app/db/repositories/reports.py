from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Report


class ReportRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, report: Report) -> Report:
        self.session.add(report)
        return report