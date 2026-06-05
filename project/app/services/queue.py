import json
from redis.asyncio import Redis


class QueueService:
    KEY = "queue:waiting"

    def __init__(self, redis: Redis):
        self.redis = redis

    def _encode(self, user_id: int, gender: str, search_filter: str, priority: int, ts: float) -> str:
        return json.dumps(
            {
                "user_id": user_id,
                "gender": gender,
                "filter": search_filter,
                "priority": priority,
                "ts": ts,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    def _decode(self, raw: str) -> dict:
        return json.loads(raw)

    async def push(self, user_id: int, gender: str, search_filter: str, priority: int, ts: float) -> None:
        await self.redis.rpush(self.KEY, self._encode(user_id, gender, search_filter, priority, ts))

    async def items(self) -> list[tuple[str, dict]]:
        raws = await self.redis.lrange(self.KEY, 0, -1)
        return [(raw, self._decode(raw)) for raw in raws]

    async def remove_user(self, user_id: int) -> int:
        items = await self.redis.lrange(self.KEY, 0, -1)
        removed = 0

        for raw in items:
            item = self._decode(raw)
            if int(item["user_id"]) == int(user_id):
                removed += await self.redis.lrem(self.KEY, 1, raw)

        return removed

    async def clear(self) -> None:
        await self.redis.delete(self.KEY)
