"""
Trends cache service for caching X trending topics with TTL-based expiration.

Provides:
- In-memory caching per WOEID
- TTL-based expiration (default 15 minutes)
- Thread-safe operations
- Background cleanup task
- Stale cache fallback for rate limit handling
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CachedTrends:
    """Cached trending topics with expiration metadata."""
    trends: List[Dict[str, Any]]
    cached_at: datetime
    expires_at: datetime

    def is_expired(self) -> bool:
        """Check if cache entry is expired."""
        return datetime.now(timezone.utc) >= self.expires_at

    def is_stale(self) -> bool:
        """Alias for is_expired() for clarity."""
        return self.is_expired()


class TrendsCache:
    """
    In-memory cache for trending topics by WOEID with TTL-based expiration.

    Features:
    - Thread-safe caching
    - Configurable TTL (default 15 minutes)
    - Background cleanup task
    - Stale cache retrieval for rate limit handling
    - Cache hit/miss metrics
    """

    def __init__(self, ttl_seconds: int = 900):
        """
        Initialize trends cache.

        Args:
            ttl_seconds: Time-to-live for cache entries in seconds (default: 900 = 15 minutes)
        """
        self._cache: Dict[int, CachedTrends] = {}
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()

        # Metrics
        self._hits = 0
        self._misses = 0
        self._stale_hits = 0

        logger.info(f"TrendsCache initialized with {ttl_seconds}s TTL")

    def get(self, woeid: int, allow_stale: bool = False) -> Optional[List[Dict[str, Any]]]:
        """
        Get cached trends for a WOEID if not expired.

        Args:
            woeid: WOEID to lookup
            allow_stale: If True, return stale cache entries (for rate limit fallback)

        Returns:
            List of trend dicts if found and valid, None otherwise
        """
        with self._lock:
            if woeid not in self._cache:
                self._misses += 1
                logger.debug(f"Cache miss for WOEID {woeid}")
                return None

            cached = self._cache[woeid]

            # Check if expired
            if cached.is_expired():
                if allow_stale:
                    self._stale_hits += 1
                    logger.debug(f"Stale cache hit for WOEID {woeid}")
                    return cached.trends
                else:
                    self._misses += 1
                    logger.debug(f"Cache expired for WOEID {woeid}")
                    return None

            # Valid cache hit
            self._hits += 1
            logger.debug(f"Cache hit for WOEID {woeid}")
            return cached.trends

    def set(self, woeid: int, trends: List[Dict[str, Any]]) -> None:
        """
        Cache trends for a WOEID.

        Args:
            woeid: WOEID to cache
            trends: List of trend dicts to cache
        """
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self._ttl_seconds)

        cached = CachedTrends(
            trends=trends,
            cached_at=now,
            expires_at=expires_at
        )

        with self._lock:
            self._cache[woeid] = cached

        logger.info(
            f"Cached {len(trends)} trends for WOEID {woeid} "
            f"(expires at {expires_at.strftime('%H:%M:%S UTC')})"
        )

    def get_metadata(self, woeid: int) -> Optional[Dict[str, Any]]:
        """
        Get cache metadata for a WOEID without returning the actual trends.

        Args:
            woeid: WOEID to lookup

        Returns:
            Dict with cached_at, expires_at, is_expired, is_stale, or None if not cached
        """
        with self._lock:
            if woeid not in self._cache:
                return None

            cached = self._cache[woeid]
            return {
                "cached_at": cached.cached_at,
                "expires_at": cached.expires_at,
                "is_expired": cached.is_expired(),
                "is_stale": cached.is_stale(),
                "trend_count": len(cached.trends)
            }

    def invalidate(self, woeid: int) -> bool:
        """
        Invalidate (remove) cached trends for a WOEID.

        Args:
            woeid: WOEID to invalidate

        Returns:
            True if entry was removed, False if not found
        """
        with self._lock:
            if woeid in self._cache:
                del self._cache[woeid]
                logger.info(f"Invalidated cache for WOEID {woeid}")
                return True
            return False

    def clear(self) -> int:
        """
        Clear all cached entries.

        Returns:
            Number of entries cleared
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Cleared {count} cached entries")
            return count

    def cleanup_expired(self) -> int:
        """
        Remove all expired cache entries.

        Returns:
            Number of entries removed
        """
        with self._lock:
            expired_woeids = [
                woeid for woeid, cached in self._cache.items()
                if cached.is_expired()
            ]

            for woeid in expired_woeids:
                del self._cache[woeid]

            if expired_woeids:
                logger.info(f"Cleaned up {len(expired_woeids)} expired cache entries")

            return len(expired_woeids)

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dict with cache metrics
        """
        with self._lock:
            total_entries = len(self._cache)
            expired_entries = sum(1 for cached in self._cache.values() if cached.is_expired())
            total_requests = self._hits + self._misses
            hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0

            return {
                "total_entries": total_entries,
                "expired_entries": expired_entries,
                "valid_entries": total_entries - expired_entries,
                "cache_hits": self._hits,
                "cache_misses": self._misses,
                "stale_hits": self._stale_hits,
                "total_requests": total_requests,
                "hit_rate_percent": round(hit_rate, 2),
                "ttl_seconds": self._ttl_seconds
            }

    async def start_cleanup_task(self):
        """
        Start background task to cleanup expired entries every 5 minutes.

        This is an async task that should be started with asyncio.create_task()
        in the application lifespan.
        """
        logger.info("Starting background cache cleanup task (runs every 5 minutes)")

        while True:
            await asyncio.sleep(300)  # 5 minutes
            try:
                removed = self.cleanup_expired()
                if removed > 0:
                    logger.info(f"Background cleanup removed {removed} expired entries")
            except Exception as e:
                logger.error(f"Error in background cleanup task: {e}")
