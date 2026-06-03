from redis.asyncio import Redis


class RateLimitService:
    def __init__(self, redis: Redis, max_actions: int = 5, window_seconds: int = 60):
        self.redis = redis
        self.max_actions = max_actions
        self.window_seconds = window_seconds

    def _key(self, user_id: int) -> str:
        return f"rate_limit:{user_id}"

    async def check(self, user_id: int) -> bool:
        key = self._key(user_id)
        current = await self.redis.incr(key)
        if current == 1:
            await self.redis.expire(key, self.window_seconds)
        return current <= self.max_actions