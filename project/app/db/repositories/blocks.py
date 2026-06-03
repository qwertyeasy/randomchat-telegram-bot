from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Block


class BlockRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, block: Block) -> Block:
        self.session.add(block)
        return block