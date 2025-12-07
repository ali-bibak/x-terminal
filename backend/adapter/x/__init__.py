"""
X (Twitter) API Adapter for X Terminal.

Provides methods to fetch posts as Tick objects for aggregation into bars.
Uses the Twitter API v2 Recent Search endpoint.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests
from dotenv import load_dotenv

from ..models import Tick
from ..rate_limiter import RateLimiter, RateLimitConfig

# Import monitoring (lazy to avoid circular imports)
_monitor = None

def _get_monitor():
    global _monitor
    if _monitor is None:
        try:
            from monitoring import monitor
            _monitor = monitor
        except ImportError:
            _monitor = None
    return _monitor

load_dotenv()

logger = logging.getLogger(__name__)


class XAdapterError(Exception):
    """Base exception for XAdapter errors."""
    pass


class XAuthenticationError(XAdapterError):
    """Raised when authentication fails."""
    pass


class XRateLimitError(XAdapterError):
    """Raised when rate limit is exceeded."""
    def __init__(self, message: str, reset_time: int = None, remaining: int = None, limit: int = None):
        super().__init__(message)
        self.reset_time = reset_time  # Unix timestamp when limit resets
        self.remaining = remaining    # Remaining requests in window
        self.limit = limit            # Total requests allowed in window


class XAPIError(XAdapterError):
    """Raised when API returns an error."""
    def __init__(self, message: str, status_code: int = None, response_text: str = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class XAdapter:
    """
    Adapter for X (Twitter) API v2.
    
    Provides methods to search for posts and convert them to Tick objects
    for use with the BarAggregator.
    
    Usage:
        adapter = XAdapter()  # Uses X_BEARER_TOKEN env var
        ticks = adapter.search_recent("$TSLA", topic="$TSLA", minutes=5)
    """
    
    BASE_URL = "https://api.x.com/2"
    
    # Internal rate limit - set high to let X API handle actual limiting
    # X API will return 429 when you hit their real limit
    DEFAULT_RATE_LIMIT = RateLimitConfig(
        requests_per_window=1000,
        window_seconds=60,
        strategy="sliding_window"
    )

    def __init__(
        self,
        bearer_token: Optional[str] = None,
        rate_limiter: Optional[RateLimiter] = None,
        skip_rate_limit: bool = False
    ):
        """
        Initialize the X adapter.
        
        Args:
            bearer_token: X API bearer token (or set X_BEARER_TOKEN env var)
            rate_limiter: Optional shared rate limiter
            skip_rate_limit: If True, skip internal rate limiting (X API still enforces its own)
        """
        self._skip_rate_limit = skip_rate_limit
        self.bearer_token = bearer_token or os.environ.get("X_BEARER_TOKEN")
        
        if not self.bearer_token:
            logger.warning("No X_BEARER_TOKEN provided - adapter will fail on API calls")
            self._is_configured = False
        else:
            self._is_configured = True
        
        self.headers = {
            "Authorization": f"Bearer {self.bearer_token}" if self.bearer_token else "",
        }
        
        # Setup rate limiter
        self.rate_limiter = rate_limiter or RateLimiter()
        if "x_search" not in self.rate_limiter.configs:
            self.rate_limiter.configure_limit("x_search", self.DEFAULT_RATE_LIMIT)

        # Configure rate limiter for trends endpoint (75 requests per 15 minutes)
        if "x_trends" not in self.rate_limiter.configs:
            self.rate_limiter.configure_limit("x_trends", RateLimitConfig(
                requests_per_window=75,
                window_seconds=900,  # 15 minutes
                strategy="sliding_window"
            ))
        
        # Track rate limit status from API responses
        self._rate_limit_status = {
            "limit": None,
            "remaining": None,
            "reset_time": None,
            "last_updated": None
        }

    @property
    def is_configured(self) -> bool:
        """Check if adapter is properly configured with credentials."""
        return self._is_configured

    def get_rate_limit_status(self) -> dict:
        """
        Get the current rate limit status from the last API response.
        
        Returns:
            Dict with limit, remaining, reset_time, and seconds_until_reset
        """
        status = self._rate_limit_status.copy()
        
        if status["reset_time"]:
            now = datetime.now(timezone.utc)
            reset_dt = datetime.fromtimestamp(status["reset_time"], tz=timezone.utc)
            status["seconds_until_reset"] = max(0, int((reset_dt - now).total_seconds()))
            status["reset_time_str"] = reset_dt.strftime("%H:%M:%S UTC")
        else:
            status["seconds_until_reset"] = None
            status["reset_time_str"] = None
        
        return status

    def _update_rate_limit_status(self, response) -> None:
        """Update rate limit status from response headers."""
        headers = response.headers
        
        reset = headers.get("x-rate-limit-reset")
        remaining = headers.get("x-rate-limit-remaining")
        limit = headers.get("x-rate-limit-limit")
        
        if reset:
            self._rate_limit_status["reset_time"] = int(reset)
        if remaining:
            self._rate_limit_status["remaining"] = int(remaining)
        if limit:
            self._rate_limit_status["limit"] = int(limit)
        
        self._rate_limit_status["last_updated"] = datetime.now(timezone.utc)
        
        # Log warning if running low
        if self._rate_limit_status["remaining"] is not None:
            remaining = self._rate_limit_status["remaining"]
            if remaining <= 5:
                logger.warning(f"X API rate limit nearly exhausted: {remaining} requests remaining")
            elif remaining <= 20:
                logger.info(f"X API rate limit: {remaining} requests remaining")

    def _format_time(self, dt: datetime) -> str:
        """Format datetime for X API (ISO 8601 with Z suffix)."""
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _get_time_bounds(self, minutes: int) -> tuple[str, str]:
        """
        Get start and end time bounds for a search.
        
        X API requires end_time to be at least 10 seconds before now.
        """
        now = datetime.now(timezone.utc)
        safe_end = now - timedelta(seconds=20)  # 20 second buffer
        start = safe_end - timedelta(minutes=minutes)
        
        return self._format_time(start), self._format_time(safe_end)

    def _parse_tweet_to_tick(
        self,
        tweet: dict,
        users_map: dict,
        topic: str
    ) -> Tick:
        """Convert a raw tweet response to a Tick object."""
        author_id = tweet.get("author_id")
        user = users_map.get(author_id, {})
        username = user.get("username", "unknown")
        
        # Parse timestamp
        created_at = tweet.get("created_at")
        if created_at:
            timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        else:
            timestamp = datetime.now(timezone.utc)
        
        # Extract metrics
        public_metrics = tweet.get("public_metrics", {})
        metrics = {
            "like_count": public_metrics.get("like_count", 0),
            "retweet_count": public_metrics.get("retweet_count", 0),
            "reply_count": public_metrics.get("reply_count", 0),
            "quote_count": public_metrics.get("quote_count", 0),
            "impression_count": public_metrics.get("impression_count", 0),
        }
        
        return Tick(
            id=tweet["id"],
            author=username,
            text=tweet.get("text", ""),
            timestamp=timestamp,
            metrics=metrics,
            topic=topic
        )

    def search_recent(
        self,
        query: str,
        topic: str,
        minutes: int = 10,
        max_results: int = 100,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Tick]:
        """
        Search for recent tweets matching a query and return as Tick objects.
        
        Args:
            query: Search query (e.g., "$TSLA" or "bitcoin -is:retweet")
            topic: Topic label to assign to resulting Ticks
            minutes: How far back to search (default: 10 minutes)
            max_results: Maximum results to return (10-100)
            start_time: Optional explicit start time (overrides minutes)
            end_time: Optional explicit end time
        
        Returns:
            List of Tick objects
        
        Raises:
            XAuthenticationError: If not configured with bearer token
            XRateLimitError: If rate limit exceeded
            XAPIError: If API returns an error
        """
        if not self._is_configured:
            raise XAuthenticationError("X adapter not configured - set X_BEARER_TOKEN")
        
        # Validate max_results
        max_results = max(10, min(100, max_results))
        
        # Wait for rate limit (if enabled)
        if not self._skip_rate_limit:
            self.rate_limiter.wait_if_needed("x_search")
        
        # Build time bounds
        if start_time and end_time:
            # X API requires end_time to be at least 10 seconds before now
            now = datetime.now(timezone.utc)
            min_allowed_end = now - timedelta(seconds=12)  # 12 second buffer for safety
            
            if end_time > min_allowed_end:
                # Bar is too recent to query - X API will reject it
                seconds_until_ready = (end_time - min_allowed_end).total_seconds()
                logger.warning(
                    f"Bar end_time {end_time.strftime('%H:%M:%S')} is too recent for X API. "
                    f"Need to wait ~{seconds_until_ready:.0f}s. Returning empty results."
                )
                return []
            
            start_str = self._format_time(start_time)
            end_str = self._format_time(end_time)
        else:
            start_str, end_str = self._get_time_bounds(minutes)
        
        # Build query - exclude retweets by default if not specified
        if "-is:retweet" not in query.lower():
            query = f"{query} -is:retweet"
        
        params = {
            "query": query,
            "start_time": start_str,
            "end_time": end_str,
            "max_results": max_results,
            "tweet.fields": "id,text,created_at,author_id,public_metrics,lang",
            "expansions": "author_id",
            "user.fields": "username,name,verified"
        }
        
        url = f"{self.BASE_URL}/tweets/search/recent"
        
        try:
            start_time_ms = time.time() * 1000
            response = requests.get(
                url,
                headers=self.headers,
                params=params,
                timeout=15
            )
            latency_ms = (time.time() * 1000) - start_time_ms
            
            # Always update rate limit status from headers (even on errors)
            self._update_rate_limit_status(response)
            
            # Record X API call in monitoring
            mon = _get_monitor()
            if mon:
                is_error = response.status_code >= 400
                mon.metrics.record_x_api_call(latency_ms, error=is_error)
                if is_error:
                    from monitoring import EventType
                    mon.activity.add_event(EventType.ERROR, topic=topic, error=f"X API {response.status_code}")
            
            # Handle specific error codes
            if response.status_code == 401:
                raise XAuthenticationError("Invalid or expired bearer token")
            elif response.status_code == 429:
                # Extract rate limit info from headers
                reset_time = response.headers.get("x-rate-limit-reset")
                remaining = response.headers.get("x-rate-limit-remaining")
                limit = response.headers.get("x-rate-limit-limit")
                raise XRateLimitError(
                    "X API rate limit exceeded",
                    reset_time=int(reset_time) if reset_time else None,
                    remaining=int(remaining) if remaining else None,
                    limit=int(limit) if limit else None
                )
            elif response.status_code >= 400:
                raise XAPIError(
                    f"X API error: {response.status_code}",
                    status_code=response.status_code,
                    response_text=response.text
                )
            
            response.raise_for_status()
            data = response.json()
            
            # Check for empty results
            if "data" not in data or not data["data"]:
                logger.info(f"No tweets found for query '{query}' in the last {minutes} minutes")
                return []
            
            # Build users map for author lookup
            users_map = {}
            for user in data.get("includes", {}).get("users", []):
                users_map[user["id"]] = user
            
            # Convert to Tick objects
            ticks = []
            for tweet in data["data"]:
                tick = self._parse_tweet_to_tick(tweet, users_map, topic)
                ticks.append(tick)
            
            logger.info(f"Fetched {len(ticks)} ticks for query '{query}'")
            
            # Record successful X API call event
            mon = _get_monitor()
            if mon:
                from monitoring import EventType
                mon.activity.add_event(
                    EventType.X_API_CALL, 
                    topic=topic, 
                    query=query,
                    ticks_fetched=len(ticks),
                    latency_ms=round(latency_ms, 1)
                )
            
            return ticks
            
        except requests.exceptions.Timeout:
            raise XAPIError("X API request timed out")
        except requests.exceptions.ConnectionError:
            raise XAPIError("Failed to connect to X API")
        except (XAuthenticationError, XRateLimitError, XAPIError):
            raise
        except Exception as e:
            raise XAPIError(f"Unexpected error: {e}")

    def search_for_bar(
        self,
        query: str,
        topic: str,
        start_time: datetime,
        end_time: datetime,
        max_results: int = 100
    ) -> List[Tick]:
        """
        Search for tweets within a specific time window (for bar creation).
        
        Convenience method for BarAggregator to fetch ticks for a closed bar.
        
        Args:
            query: Search query
            topic: Topic label
            start_time: Bar start time
            end_time: Bar end time
            max_results: Maximum results (10-100)
        
        Returns:
            List of Tick objects within the time window
        """
        return self.search_recent(
            query=query,
            topic=topic,
            start_time=start_time,
            end_time=end_time,
            max_results=max_results
        )

    def get_tweet_counts(
        self,
        query: str,
        granularity: str = "minute",
        minutes: int = 60
    ) -> List[dict]:
        """
        Get tweet counts over time for a query.
        
        Note: Requires Academic Research or Enterprise access.
        
        Args:
            query: Search query
            granularity: "minute", "hour", or "day"
            minutes: How far back to look
        
        Returns:
            List of count objects with start, end, and tweet_count
        """
        if not self._is_configured:
            raise XAuthenticationError("X adapter not configured - set X_BEARER_TOKEN")
        
        if not self._skip_rate_limit:
            self.rate_limiter.wait_if_needed("x_search")
        
        start_str, end_str = self._get_time_bounds(minutes)
        
        params = {
            "query": query,
            "start_time": start_str,
            "end_time": end_str,
            "granularity": granularity
        }
        
        url = f"{self.BASE_URL}/tweets/counts/recent"
        
        try:
            response = requests.get(
                url,
                headers=self.headers,
                params=params,
                timeout=15
            )
            
            if response.status_code == 401:
                raise XAuthenticationError("Invalid or expired bearer token")
            elif response.status_code == 429:
                raise XRateLimitError("X API rate limit exceeded")
            elif response.status_code >= 400:
                raise XAPIError(
                    f"X API error: {response.status_code}",
                    status_code=response.status_code,
                    response_text=response.text
                )
            
            data = response.json()
            return data.get("data", [])
            
        except (XAuthenticationError, XRateLimitError, XAPIError):
            raise
        except Exception as e:
            raise XAPIError(f"Unexpected error: {e}")


    def get_trending_topics(
        self,
        woeid: int,
        limit: int = 10
    ) -> List[dict]:
        """
        Fetch trending topics for a specific location by WOEID.

        Uses X API v2: GET /2/trends/by/woeid/{woeid}

        Args:
            woeid: Where On Earth ID for location (1 = Worldwide)
            limit: Maximum number of trends to return (default: 10)

        Returns:
            List of trending topic dictionaries with:
            - name: Topic name/hashtag
            - url: X URL for the topic
            - query: Search query string
            - tweet_volume: Number of tweets (may be None)
            - rank: Ranking position (1-based)

        Raises:
            XAuthenticationError: If not configured with bearer token
            XRateLimitError: If rate limit exceeded
            XAPIError: If API returns an error
        """
        if not self._is_configured:
            raise XAuthenticationError("X adapter not configured - set X_BEARER_TOKEN")

        # Wait for rate limit (if enabled)
        if not self._skip_rate_limit:
            self.rate_limiter.wait_if_needed("x_trends")

        url = f"{self.BASE_URL}/trends/by/woeid/{woeid}"

        try:
            start_time_ms = time.time() * 1000
            response = requests.get(
                url,
                headers=self.headers,
                timeout=15
            )
            latency_ms = (time.time() * 1000) - start_time_ms

            # Always update rate limit status from headers (even on errors)
            self._update_rate_limit_status(response)

            # Record X API call in monitoring
            mon = _get_monitor()
            if mon:
                is_error = response.status_code >= 400
                mon.metrics.record_x_api_call(latency_ms, error=is_error)
                if is_error:
                    from monitoring import EventType
                    mon.activity.add_event(
                        EventType.ERROR,
                        topic="trends",
                        error=f"X API {response.status_code}"
                    )

            # Handle specific error codes
            if response.status_code == 401:
                raise XAuthenticationError("Invalid or expired bearer token")
            elif response.status_code == 429:
                # Extract rate limit info from headers
                reset_time = response.headers.get("x-rate-limit-reset")
                remaining = response.headers.get("x-rate-limit-remaining")
                limit_val = response.headers.get("x-rate-limit-limit")
                raise XRateLimitError(
                    "X API rate limit exceeded",
                    reset_time=int(reset_time) if reset_time else None,
                    remaining=int(remaining) if remaining else None,
                    limit=int(limit_val) if limit_val else None
                )
            elif response.status_code == 404:
                raise XAPIError(
                    f"Invalid WOEID: {woeid}",
                    status_code=404,
                    response_text=response.text
                )
            elif response.status_code >= 400:
                raise XAPIError(
                    f"X API error: {response.status_code}",
                    status_code=response.status_code,
                    response_text=response.text
                )

            response.raise_for_status()
            data = response.json()

            # X API v2 trends response format:
            # { "data": [{ "trend_name": "...", "tweet_count": ... }, ...] }
            if "data" not in data or not data["data"]:
                logger.info(f"No trending topics found for WOEID {woeid}")
                return []

            trends_data = data["data"]

            # Format trends
            trends = []
            for idx, trend in enumerate(trends_data[:limit], start=1):
                trend_name = trend.get("trend_name", "")
                # Create search query from trend name
                query = trend_name.replace("#", "%23").replace(" ", "%20")

                trends.append({
                    "name": trend_name,
                    "url": f"https://x.com/search?q={query}",
                    "query": trend_name,  # Keep original for searching
                    "tweet_volume": trend.get("tweet_count"),
                    "rank": idx
                })

            logger.info(f"Fetched {len(trends)} trending topics for WOEID {woeid}")

            # Record successful X API call event
            mon = _get_monitor()
            if mon:
                from monitoring import EventType
                mon.activity.add_event(
                    EventType.X_API_CALL,
                    topic="trends",
                    woeid=woeid,
                    trends_count=len(trends),
                    latency_ms=round(latency_ms, 1)
                )

            return trends

        except requests.exceptions.Timeout:
            raise XAPIError("X API request timed out")
        except requests.exceptions.ConnectionError:
            raise XAPIError("Failed to connect to X API")
        except (XAuthenticationError, XRateLimitError, XAPIError):
            raise
        except Exception as e:
            raise XAPIError(f"Unexpected error: {e}")


__all__ = [
    "XAdapter",
    "XAdapterError",
    "XAuthenticationError",
    "XRateLimitError",
    "XAPIError",
    "Tick",  # Re-export for convenience
]

