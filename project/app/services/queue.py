import json
from redis.asyncio import Redis


class QueueService:
    def __init__(self, redis: Redis):
        self.redis = redis

    def _key(self, search_filter: str) -> str:
        return f"queue:{search_filter}"

    def _encode(self, user_id: int, priority: int, ts: float) -> str:
        return json.dumps(
            {"user_id": user_id, "priority": priority, "ts": ts},
            separators=(",", ":"),
            sort_keys=True,
        )

    def _decode(self, raw: str) -> dict:
        return json.loads(raw)

    async def push(self, search_filter: str, user_id: int, priority: int, ts: float) -> None:
        await self.redis.rpush(self._key(search_filter), self._encode(user_id, priority, ts))

    async def pop(self, search_filter: str) -> dict | None:
        raw = await self.redis.lpop(self._key(search_filter))
        return self._decode(raw) if raw else None

    async def remove_user(self, search_filter: str, user_id: int) -> int:
        key = self._key(search_filter)
        items = await self.redis.lrange(key, 0, -1)
        removed = 0

        for raw in items:
            item = self._decode(raw)
            if int(item["user_id"]) == int(user_id):
                removed += await self.redis.lrem(key, 1, raw)

        return removed

    async def clear(self, search_filter: str) -> None:
        await self.redis.delete(self._key(search_filter))