"""
Flexible rate limiter supporting multiple APIs with different requirements.

Supports different time windows, request categories, and rate limiting strategies.
Designed to be shared between X API and Grok API adapters.
"""

from __future__ import annotations

import time
import logging
from typing import Dict, List, Optional, Literal
from dataclasses import dataclass
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for a specific rate limit."""
    requests_per_window: int
    window_seconds: int
    strategy: Literal["sliding_window", "fixed_window", "token_bucket"] = "sliding_window"


class RateLimiter:
    """
    Flexible rate limiter supporting multiple APIs and endpoint categories.

    Features:
    - Multiple time windows (per minute, 15-min, hourly, daily)
    - Different limits per category (e.g., search vs user_lookup vs ai_generation)
    - Configurable strategies (sliding window, fixed window, token bucket)
    - Shared state across multiple API clients
    """

    def __init__(self):
        # category -> list of (timestamp, count) tuples for sliding window
        self.sliding_windows: Dict[str, List[float]] = defaultdict(list)

        # category -> (window_start, count) for fixed window
        self.fixed_windows: Dict[str, tuple[int, int]] = {}

        # category -> available tokens for token bucket
        self.token_buckets: Dict[str, float] = {}

        # Configuration per category
        self.configs: Dict[str, RateLimitConfig] = {}

        # Last refill times for token buckets
        self.last_refill: Dict[str, float] = {}

    def configure_limit(self, category: str, config: RateLimitConfig) -> None:
        """Configure rate limiting for a specific category."""
        self.configs[category] = config

        if config.strategy == "token_bucket":
            self.token_buckets[category] = config.requests_per_window
            self.last_refill[category] = time.time()

        logger.info(f"Configured rate limit for {category}: {config.requests_per_window} req/{config.window_seconds}s ({config.strategy})")

    def wait_if_needed(self, category: str = "default") -> None:
        """
        Wait if the rate limit would be exceeded for the given category.

        Args:
            category: Rate limit category (e.g., "x_search", "x_user", "grok_fast", "grok_reasoning")
        """
        if category not in self.configs:
            logger.warning(f"No rate limit configured for category '{category}', allowing request")
            return

        config = self.configs[category]

        if config.strategy == "sliding_window":
            self._wait_sliding_window(category, config)
        elif config.strategy == "fixed_window":
            self._wait_fixed_window(category, config)
        elif config.strategy == "token_bucket":
            self._wait_token_bucket(category, config)

    def _wait_sliding_window(self, category: str, config: RateLimitConfig) -> None:
        """Sliding window rate limiting."""
        current_time = time.time()

        # Remove timestamps outside the window
        window_times = self.sliding_windows[category]
        window_times[:] = [t for t in window_times if current_time - t < config.window_seconds]

        # Check if we're at the limit
        if len(window_times) >= config.requests_per_window:
            # Wait until the oldest request is outside the window
            oldest_time = min(window_times)
            wait_time = config.window_seconds - (current_time - oldest_time)

            if wait_time > 0:
                logger.info(f"Rate limiting {category}: waiting {wait_time:.2f} seconds")
                time.sleep(wait_time)

                # Recalculate after waiting
                current_time = time.time()
                window_times[:] = [t for t in window_times if current_time - t < config.window_seconds]

        # Record this request
        window_times.append(current_time)

    def _wait_fixed_window(self, category: str, config: RateLimitConfig) -> None:
        """Fixed window rate limiting."""
        current_time = time.time()
        window_start = int(current_time / config.window_seconds) * config.window_seconds

        if category in self.fixed_windows:
            stored_window, count = self.fixed_windows[category]
            if stored_window == window_start:
                # Same window
                if count >= config.requests_per_window:
                    # Wait for next window
                    wait_time = (stored_window + config.window_seconds) - current_time
                    if wait_time > 0:
                        logger.info(f"Rate limiting {category}: waiting {wait_time:.2f} seconds for next window")
                        time.sleep(wait_time)
                        # Reset for new window after waiting
                        window_start = int(time.time() / config.window_seconds) * config.window_seconds
                        count = 0
                else:
                    count += 1
            else:
                # New window
                count = 1
        else:
            count = 1

        self.fixed_windows[category] = (window_start, count)

    def _wait_token_bucket(self, category: str, config: RateLimitConfig) -> None:
        """Token bucket rate limiting."""
        current_time = time.time()

        # Refill tokens based on time passed
        if category in self.last_refill:
            time_passed = current_time - self.last_refill[category]
            refill_rate = config.requests_per_window / config.window_seconds  # tokens per second
            tokens_to_add = time_passed * refill_rate

            current_tokens = self.token_buckets[category]
            self.token_buckets[category] = min(config.requests_per_window, current_tokens + tokens_to_add)

        self.last_refill[category] = current_time

        # Check if we have a token available
        if self.token_buckets[category] < 1:
            # Calculate wait time for next token
            refill_rate = config.requests_per_window / config.window_seconds
            wait_time = (1 - self.token_buckets[category]) / refill_rate

            logger.info(f"Rate limiting {category}: waiting {wait_time:.2f} seconds for token")
            time.sleep(wait_time)

            # Recalculate after waiting
            current_time = time.time()
            time_passed = current_time - self.last_refill[category]
            tokens_to_add = time_passed * refill_rate
            self.token_buckets[category] = min(config.requests_per_window, self.token_buckets[category] + tokens_to_add)
            self.last_refill[category] = current_time

        # Consume a token
        self.token_buckets[category] -= 1

    def get_remaining_requests(self, category: str, time_window_seconds: Optional[int] = None) -> int:
        """
        Get estimated remaining requests for a category in the given time window.

        Args:
            category: Rate limit category
            time_window_seconds: Time window to check (defaults to category's window)

        Returns:
            Estimated number of remaining requests allowed
        """
        if category not in self.configs:
            return float('inf')

        config = self.configs[category]
        window_seconds = time_window_seconds or config.window_seconds

        if config.strategy == "sliding_window":
            current_time = time.time()
            window_times = self.sliding_windows[category]
            recent_times = [t for t in window_times if current_time - t < window_seconds]
            return max(0, config.requests_per_window - len(recent_times))

        elif config.strategy == "token_bucket":
            return max(0, int(self.token_buckets.get(category, config.requests_per_window)))

        # For fixed window, this is approximate
        return config.requests_per_window // 2  # Conservative estimate


# Pre-configured rate limiter instances for common API patterns
def create_x_api_limiter() -> RateLimiter:
    """Create a rate limiter configured for X API limits."""
    limiter = RateLimiter()

    # X API v2 rate limits (app-only, subject to change)
    # Search tweets: 300 requests per 15 minutes
    limiter.configure_limit("x_search", RateLimitConfig(
        requests_per_window=300,
        window_seconds=900,  # 15 minutes
        strategy="sliding_window"
    ))

    # User lookup: 300 requests per 15 minutes
    limiter.configure_limit("x_user_lookup", RateLimitConfig(
        requests_per_window=300,
        window_seconds=900,
        strategy="sliding_window"
    ))

    # Recent search (full archive): 1 request per second
    limiter.configure_limit("x_recent_search", RateLimitConfig(
        requests_per_window=60,
        window_seconds=60,
        strategy="token_bucket"
    ))

    return limiter


def create_grok_api_limiter() -> RateLimiter:
    """Create a rate limiter configured for Grok API limits."""
    limiter = RateLimiter()

    # Grok API rate limits (estimated, adjust based on actual limits)
    # Fast model: higher rate limit for quick responses
    limiter.configure_limit("grok_fast", RateLimitConfig(
        requests_per_window=60,
        window_seconds=60,
        strategy="sliding_window"
    ))

    # reasoning model: lower rate limit for complex reasoning
    limiter.configure_limit("grok_reasoning", RateLimitConfig(
        requests_per_window=30,
        window_seconds=60,
        strategy="sliding_window"
    ))

    return limiter


def create_shared_limiter() -> RateLimiter:
    """Create a shared rate limiter for both X and Grok APIs."""
    limiter = RateLimiter()

    # X API limits
    limiter.configure_limit("x_search", RateLimitConfig(300, 900, "sliding_window"))
    limiter.configure_limit("x_user_lookup", RateLimitConfig(300, 900, "sliding_window"))
    limiter.configure_limit("x_recent_search", RateLimitConfig(60, 60, "token_bucket"))

    # Grok API limits
    limiter.configure_limit("grok_fast", RateLimitConfig(60, 60, "sliding_window"))
    limiter.configure_limit("grok_reasoning", RateLimitConfig(30, 60, "sliding_window"))

    return limiter


# Global shared instance
shared_limiter = create_shared_limiter()
