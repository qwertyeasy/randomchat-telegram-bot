import json
from redis.asyncio import Redis


class QueueService:
    def __init__(self, redis: Redis):
        self.redis = redis

    def _key(self, search_filter: str) -> str:
        return f"queue:{search_filter}"

    async def push(self, search_filter: str, user_id: int, priority: int, ts: float) -> None:
        payload = json.dumps({"user_id": user_id, "priority": priority, "ts": ts})
        await self.redis.rpush(self._key(search_filter), payload)

    async def pop(self, search_filter: str) -> dict | None:
        raw = await self.redis.lpop(self._key(search_filter))
        return json.loads(raw) if raw else None

    async def remove_user(self, search_filter: str, user_id: int) -> None:
        key = self._key(search_filter)
        items = await self.redis.lrange(key, 0, -1)
        await self.redis.delete(key)
        for raw in items:
            item = json.loads(raw)
            if int(item["user_id"]) != user_id:
                await self.redis.rpush(key, raw)

    async def clear(self, search_filter: str) -> None:
        await self.redis.delete(self._key(search_filter))