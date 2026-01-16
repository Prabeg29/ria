import json

from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from .settings import settings


redis = Redis(host=settings.redis_host)
async_redis = AsyncRedis(host=settings.redis_host, decode_responses=True)


async def publish(job_id: str, event_type: str, data: dict = {}):
    await async_redis.xadd(
        f"analysis:stream:{job_id}",
        {
            "type": event_type,
            "payload": json.dumps(data)
        }
    )
