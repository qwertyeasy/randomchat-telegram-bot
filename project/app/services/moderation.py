from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Block, Report
from app.db.repositories.blocks import BlockRepository
from app.db.repositories.reports import ReportRepository


class ModerationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.blocks = BlockRepository(db)
        self.reports = ReportRepository(db)

    async def create_report(
        self,
        session_id,
        reporter_id: int,
        target_id: int,
        reason: str,
        attached_message: str | None = None,
    ) -> None:
        await self.reports.create(
            Report(
                session_id=session_id,
                reporter_id=reporter_id,
                target_id=target_id,
                reason=reason,
                attached_message=attached_message,
            )
        )
        await self.db.commit()

    async def ban_user(self, user_id: int, reason: str) -> None:
        await self.blocks.create(Block(user_id=user_id, reason=reason))
        await self.db.commit()