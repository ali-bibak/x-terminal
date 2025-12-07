"""
Aggregator module for X Terminal.
Contains BarAggregator for tick-to-bar aggregation and DigestService for creating topic digests.

Designed for polling-based usage:
1. External poller fetches ticks for a time window
2. Passes ticks to BarAggregator.create_bar()
3. BarAggregator stores bar and generates summary via GrokAdapter
4. DigestService creates digests from stored bars
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from collections import defaultdict

from pydantic import BaseModel, Field

from adapter.grok import GrokAdapter, BarSummary, TopicDigest
from adapter.models import Tick

logger = logging.getLogger(__name__)


# Resolution constants (in seconds)
RESOLUTION_MAP = {
    "1m": 60,
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
}


class Bar(BaseModel):
    """
    A time-bucketed aggregate for a single topic.
    Contains aggregated metrics and an LLM summary.
    """
    topic: str = Field(description="Topic this bar belongs to")
    resolution: str = Field(description="Time resolution (e.g., '5m')")
    start: datetime = Field(description="Start of the time window")
    end: datetime = Field(description="End of the time window")
    post_count: int = Field(default=0, description="Number of posts in this bar")
    
    # Aggregated metrics
    total_likes: int = Field(default=0, description="Sum of likes across all posts")
    total_retweets: int = Field(default=0, description="Sum of retweets across all posts")
    total_replies: int = Field(default=0, description="Sum of replies across all posts")
    total_quotes: int = Field(default=0, description="Sum of quotes across all posts")
    
    # Sample posts (stored as tick IDs)
    sample_post_ids: List[str] = Field(default_factory=list, description="IDs of sample posts")
    
    # LLM-generated summary
    summary: Optional[BarSummary] = Field(default=None, description="Grok-generated bar summary")

    def to_dict(self) -> Dict[str, Any]:
        """Convert bar to dictionary for digest API consumption."""
        return {
            "topic": self.topic,
            "resolution": self.resolution,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "post_count": self.post_count,
            "total_likes": self.total_likes,
            "total_retweets": self.total_retweets,
            "total_replies": self.total_replies,
            "total_quotes": self.total_quotes,
            "sample_post_ids": self.sample_post_ids,
            "summary": self.summary.summary if self.summary else None,
            "sentiment": self.summary.sentiment if self.summary else None,
            "key_themes": self.summary.key_themes if self.summary else [],
            "highlight_posts": self.summary.highlight_posts if self.summary else [],
        }


class BarAggregator:
    """
    Simple polling-based bar aggregator.
    
    Usage:
        aggregator = BarAggregator(grok_adapter)
        
        # At each bar close, fetch ticks and create bar
        ticks = fetch_ticks_for_window(topic, start, end)
        bar = aggregator.create_bar(topic, ticks, start, end)
        
        # Later, get bars for display
        bars = aggregator.get_bars(topic, limit=12)
    """

    def __init__(self, grok_adapter: GrokAdapter, default_resolution: str = "5m"):
        """
        Initialize the BarAggregator.
        
        Args:
            grok_adapter: GrokAdapter for generating bar summaries
            default_resolution: Default time resolution for bars
        """
        self.grok_adapter = grok_adapter
        self.default_resolution = default_resolution
        
        # In-memory storage: {topic: [Bar, Bar, ...]}
        self._bars: Dict[str, List[Bar]] = defaultdict(list)

    def create_bar(
        self,
        topic: str,
        ticks: List[Tick],
        start: datetime,
        end: datetime,
        resolution: Optional[str] = None,
        generate_summary: bool = True
    ) -> Bar:
        """
        Create a bar from ticks for a specific time window.
        
        Args:
            topic: Topic name
            ticks: List of ticks in this time window
            start: Start of the time window
            end: End of the time window
            resolution: Time resolution (e.g., "5m")
            generate_summary: Whether to generate Grok summary
        
        Returns:
            The created Bar with summary
        """
        resolution = resolution or self.default_resolution
        
        # Aggregate metrics from ticks
        total_likes = sum(t.metrics.get("like_count", 0) for t in ticks)
        total_retweets = sum(t.metrics.get("retweet_count", 0) for t in ticks)
        total_replies = sum(t.metrics.get("reply_count", 0) for t in ticks)
        total_quotes = sum(t.metrics.get("quote_count", 0) for t in ticks)
        
        # Sample post IDs (first 5)
        sample_post_ids = [t.id for t in ticks[:5]]
        
        # Create bar
        bar = Bar(
            topic=topic,
            resolution=resolution,
            start=start,
            end=end,
            post_count=len(ticks),
            total_likes=total_likes,
            total_retweets=total_retweets,
            total_replies=total_replies,
            total_quotes=total_quotes,
            sample_post_ids=sample_post_ids,
        )
        
        # Generate summary if requested and we have ticks
        if generate_summary and ticks:
            try:
                bar.summary = self.grok_adapter.summarize_bar(
                    topic=topic,
                    ticks=ticks,
                    start_time=start,
                    end_time=end
                )
                logger.info(f"Created bar for {topic} [{start} - {end}] with {len(ticks)} posts")
            except Exception as e:
                logger.error(f"Failed to generate bar summary: {e}")
        else:
            logger.info(f"Created empty bar for {topic} [{start} - {end}]")
        
        # Store bar
        self._bars[topic].append(bar)
        
        return bar

    def get_bars(self, topic: str, limit: int = 50) -> List[Bar]:
        """
        Get bars for a topic, sorted by start time (most recent first).
        
        Args:
            topic: Topic name
            limit: Maximum number of bars to return
        
        Returns:
            List of bars sorted by start time (descending)
        """
        if topic not in self._bars:
            return []
        
        # Sort by start time descending (most recent first)
        bars = sorted(self._bars[topic], key=lambda b: b.start, reverse=True)
        return bars[:limit]

    def get_latest_bar(self, topic: str) -> Optional[Bar]:
        """Get the most recent bar for a topic."""
        bars = self.get_bars(topic, limit=1)
        return bars[0] if bars else None

    def clear_topic(self, topic: str) -> None:
        """Remove all bars for a topic."""
        if topic in self._bars:
            del self._bars[topic]

    def clear_old_bars(self, max_bars_per_topic: int = 100) -> None:
        """Keep only the most recent bars per topic."""
        for topic in self._bars:
            if len(self._bars[topic]) > max_bars_per_topic:
                # Sort by start time descending and keep the most recent
                self._bars[topic] = sorted(
                    self._bars[topic],
                    key=lambda b: b.start,
                    reverse=True
                )[:max_bars_per_topic]


class DigestService:
    """
    Service for creating topic digests from aggregated bars.
    """

    def __init__(self, grok_adapter: GrokAdapter, bar_aggregator: BarAggregator):
        """
        Initialize the DigestService.
        
        Args:
            grok_adapter: GrokAdapter for generating digests
            bar_aggregator: BarAggregator to fetch bars from
        """
        self.grok_adapter = grok_adapter
        self.bar_aggregator = bar_aggregator

    def create_digest(self, topic: str, lookback_bars: int = 12) -> TopicDigest:
        """
        Create a digest for a topic based on recent bars.
        
        Args:
            topic: Topic to create digest for
            lookback_bars: Number of bars to include (default: 12)
        
        Returns:
            TopicDigest from Grok
        """
        # Get recent bars
        bars = self.bar_aggregator.get_bars(topic=topic, limit=lookback_bars)
        
        if not bars:
            logger.warning(f"No bars found for topic {topic}")
            return TopicDigest(
                topic=topic,
                generated_at=datetime.now(timezone.utc),
                time_range="No data",
                overall_summary=f"No recent activity to summarize for {topic}",
                key_developments=[],
                trending_elements=[],
                sentiment_trend="stable",
                recommendations=["Continue monitoring for activity"]
            )
        
        # Calculate lookback hours from the bars
        oldest_bar = min(bars, key=lambda b: b.start)
        newest_bar = max(bars, key=lambda b: b.end)
        time_diff = newest_bar.end - oldest_bar.start
        lookback_hours = max(1, int(time_diff.total_seconds() / 3600))
        
        # Convert bars to dict format for GrokAdapter
        bars_data = [bar.to_dict() for bar in bars]
        
        # Call Grok to generate digest
        try:
            digest = self.grok_adapter.create_topic_digest(
                topic=topic,
                bars_data=bars_data,
                lookback_hours=lookback_hours
            )
            logger.info(f"Generated digest for topic {topic} with {len(bars)} bars")
            return digest
        except Exception as e:
            logger.error(f"Failed to generate digest for {topic}: {e}")
            raise RuntimeError(f"Failed to generate digest for {topic}: {e}") from e


def get_bar_window(resolution: str = "5m") -> tuple[datetime, datetime]:
    """
    Get the current bar window boundaries based on resolution.
    
    Returns:
        Tuple of (bar_start, bar_end) for the current window
    """
    resolution_seconds = RESOLUTION_MAP.get(resolution, 300)
    now = datetime.now(timezone.utc)
    
    # Floor to resolution boundary
    ts = now.timestamp()
    bar_start_ts = int(ts // resolution_seconds) * resolution_seconds
    
    bar_start = datetime.fromtimestamp(bar_start_ts, tz=timezone.utc)
    bar_end = bar_start + timedelta(seconds=resolution_seconds)
    
    return bar_start, bar_end


def get_previous_bar_window(resolution: str = "5m") -> tuple[datetime, datetime]:
    """
    Get the previous (completed) bar window boundaries.
    
    Returns:
        Tuple of (bar_start, bar_end) for the previous window
    """
    resolution_seconds = RESOLUTION_MAP.get(resolution, 300)
    bar_start, bar_end = get_bar_window(resolution)
    
    prev_start = bar_start - timedelta(seconds=resolution_seconds)
    prev_end = bar_start
    
    return prev_start, prev_end


__all__ = [
    "Bar",
    "BarAggregator",
    "DigestService",
    "RESOLUTION_MAP",
    "Tick",  # Re-exported from adapter.models
    "get_bar_window",
    "get_previous_bar_window",
]
