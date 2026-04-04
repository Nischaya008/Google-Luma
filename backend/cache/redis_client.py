"""
Upstash Redis client for hot cache operations.

Uses the upstash-redis Python SDK (REST-based — no TCP socket needed).
Works on serverless, Render, Vercel, and any HTTP-capable environment.

All methods are fault-tolerant: failures log warnings and return None/False,
allowing callers to cascade to the next cache tier.
"""
import json
import logging
from typing import Optional, Any

from core.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """
    Singleton REST-based Redis client for Upstash.

    Usage:
        redis = RedisClient.get_instance()
        redis.set_json("key", {"data": 1}, ttl_seconds=300)
        data = redis.get_json("key")
    """

    _instance: Optional["RedisClient"] = None

    def __init__(self):
        raise RuntimeError("Use RedisClient.get_instance()")

    @classmethod
    def get_instance(cls) -> "RedisClient":
        if cls._instance is None:
            instance = object.__new__(cls)
            instance._redis = None
            instance._enabled = False
            instance._init()
            cls._instance = instance
        return cls._instance

    def _init(self):
        url = settings.REDIS_URL
        token = settings.REDIS_TOKEN

        if not url or not token or not settings.REDIS_ENABLED:
            logger.warning("Redis disabled — missing REDIS_URL/REDIS_TOKEN or REDIS_ENABLED=false")
            return

        try:
            from upstash_redis import Redis
            self._redis = Redis(url=url, token=token)
            # Verify connectivity with a ping
            self._redis.ping()
            self._enabled = True
            logger.info("Upstash Redis client initialized and connected.")
        except ImportError:
            logger.warning("upstash-redis package not installed. Redis cache disabled.")
        except Exception as e:
            logger.error(f"Redis init failed: {e}")

    @property
    def is_available(self) -> bool:
        return self._enabled and self._redis is not None

    # ── Basic Operations ─────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[str]:
        """Get a string value. Returns None on miss or error."""
        if not self.is_available:
            return None
        try:
            return self._redis.get(key)
        except Exception as e:
            logger.warning(f"Redis GET failed ({key}): {e}")
            return None

    def set(self, key: str, value: str, ttl_seconds: int = 3600) -> bool:
        """Set a string value with TTL. Returns True on success."""
        if not self.is_available:
            return False
        try:
            self._redis.set(key, value, ex=ttl_seconds)
            return True
        except Exception as e:
            logger.warning(f"Redis SET failed ({key}): {e}")
            return False

    def delete(self, key: str) -> bool:
        """Delete a key. Returns True on success."""
        if not self.is_available:
            return False
        try:
            self._redis.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Redis DEL failed ({key}): {e}")
            return False

    # ── JSON Operations ──────────────────────────────────────────────────────

    def get_json(self, key: str) -> Optional[Any]:
        """Deserialize a JSON value from Redis. Returns None on miss."""
        raw = self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Redis JSON decode failed for key: {key}")
            return None

    def set_json(self, key: str, data: Any, ttl_seconds: int = 3600) -> bool:
        """Serialize data as JSON and store with TTL."""
        try:
            serialized = json.dumps(data, default=str)
            return self.set(key, serialized, ttl_seconds)
        except (TypeError, ValueError) as e:
            logger.warning(f"Redis JSON encode failed ({key}): {e}")
            return False

    # ── Batch Operations ─────────────────────────────────────────────────────

    def get_or_set_json(
        self, key: str, factory_fn, ttl_seconds: int = 3600
    ) -> Optional[Any]:
        """
        Cache-aside pattern: return cached value or compute + store it.

        Args:
            key: Redis key
            factory_fn: Callable that returns the data to cache (called on miss)
            ttl_seconds: TTL for the cached value
        """
        cached = self.get_json(key)
        if cached is not None:
            return cached

        data = factory_fn()
        if data is not None:
            self.set_json(key, data, ttl_seconds)
        return data
