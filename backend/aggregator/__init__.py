"""
Aggregator module for X Terminal.

Architecture:
- Raw ticks are stored per topic
- Bars are generated ON-DEMAND at any resolution
- Each bar gets its own fresh Grok summary from the raw ticks
- Resolution is a query parameter, not a storage attribute

This allows:
- Instant switching between resolutions (15s, 1m, 5m, etc.)
- High-quality summaries (always from raw data, never aggregated summaries)
- Flexible demo experience
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


# Minimum resolution (15s) - respects X API constraint (10s buffer)
# All resolutions must be multiples of this for clean aggregation
MIN_RESOLUTION_SECONDS = 15

# Resolution constants (in seconds)
RESOLUTION_MAP = {
    "15s": 15,      # Minimum - 4 per minute
    "30s": 30,      # 2 per minute
    "1m": 60,       # 1 per minute
    "5m": 300,      # 1 per 5 minutes
    "15m": 900,     # 1 per 15 minutes
    "30m": 1800,    # 1 per 30 minutes
    "1h": 3600,     # 1 per hour
}

# Default resolution for display
DEFAULT_RESOLUTION = "1m"


class Bar(BaseModel):
    """
    A time-bucketed aggregate for a single topic.
    Generated on-demand from raw ticks.
    """
    topic: str = Field(description="Topic this bar belongs to")
    resolution: str = Field(description="Time resolution (e.g., '1m')")
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
    
    # LLM-generated summary (fresh from ticks, not aggregated)
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


class TickStore:
    """
    In-memory storage for raw ticks per topic.
    
    Ticks are the source of truth - bars are generated on-demand.
    """
    
    def __init__(self, max_ticks_per_topic: int = 10000):
        """
        Initialize the TickStore.
        
        Args:
            max_ticks_per_topic: Maximum ticks to keep per topic (older ones pruned)
        """
        self.max_ticks_per_topic = max_ticks_per_topic
        self._ticks: Dict[str, List[Tick]] = defaultdict(list)
        self._tick_ids: Dict[str, set] = defaultdict(set)  # For deduplication
    
    def add_ticks(self, topic: str, ticks: List[Tick]) -> int:
        """
        Add ticks for a topic (with deduplication).
        
        Args:
            topic: Topic name
            ticks: List of ticks to add
        
        Returns:
            Number of new ticks added (excluding duplicates)
        """
        added = 0
        for tick in ticks:
            if tick.id not in self._tick_ids[topic]:
                self._ticks[topic].append(tick)
                self._tick_ids[topic].add(tick.id)
                added += 1
        
        # Prune old ticks if over limit
        if len(self._ticks[topic]) > self.max_ticks_per_topic:
            # Sort by timestamp and keep most recent
            self._ticks[topic] = sorted(
                self._ticks[topic], 
                key=lambda t: t.timestamp, 
                reverse=True
            )[:self.max_ticks_per_topic]
            # Update ID set
            self._tick_ids[topic] = {t.id for t in self._ticks[topic]}
        
        return added
    
    def get_ticks(
        self, 
        topic: str, 
        start: Optional[datetime] = None,
        end: Optional[datetime] = None
    ) -> List[Tick]:
        """
        Get ticks for a topic, optionally filtered by time range.
        
        Args:
            topic: Topic name
            start: Start time (inclusive)
            end: End time (exclusive)
        
        Returns:
            List of ticks sorted by timestamp (oldest first)
        """
        ticks = self._ticks.get(topic, [])
        
        if start or end:
            filtered = []
            for tick in ticks:
                if start and tick.timestamp < start:
                    continue
                if end and tick.timestamp >= end:
                    continue
                filtered.append(tick)
            ticks = filtered
        
        return sorted(ticks, key=lambda t: t.timestamp)
    
    def get_tick_count(self, topic: str) -> int:
        """Get total tick count for a topic."""
        return len(self._ticks.get(topic, []))
    
    def get_time_range(self, topic: str) -> Optional[tuple[datetime, datetime]]:
        """Get the time range of stored ticks for a topic."""
        ticks = self._ticks.get(topic, [])
        if not ticks:
            return None
        
        sorted_ticks = sorted(ticks, key=lambda t: t.timestamp)
        return (sorted_ticks[0].timestamp, sorted_ticks[-1].timestamp)
    
    def clear_topic(self, topic: str) -> None:
        """Remove all ticks for a topic."""
        if topic in self._ticks:
            del self._ticks[topic]
        if topic in self._tick_ids:
            del self._tick_ids[topic]


class BarGenerator:
    """
    Generates bars on-demand from raw ticks.
    
    Each bar gets its own fresh Grok summary from the ticks in that window.
    """
    
    def __init__(self, grok_adapter: GrokAdapter, tick_store: TickStore):
        """
        Initialize the BarGenerator.
        
        Args:
            grok_adapter: GrokAdapter for generating summaries
            tick_store: TickStore containing raw ticks
        """
        self.grok_adapter = grok_adapter
        self.tick_store = tick_store
    
    def generate_bar(
        self,
        topic: str,
        start: datetime,
        end: datetime,
        resolution: str,
        generate_summary: bool = True
    ) -> Bar:
        """
        Generate a single bar from ticks in the given time window.
        
        Args:
            topic: Topic name
            start: Bar start time
            end: Bar end time
            resolution: Resolution label (e.g., "1m")
            generate_summary: Whether to generate Grok summary
        
        Returns:
            Bar with metrics and optional summary
        """
        # Get ticks in this window
        ticks = self.tick_store.get_ticks(topic, start=start, end=end)
        
        # Aggregate metrics
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
        
        # Generate fresh summary from ticks
        if generate_summary and ticks:
            try:
                bar.summary = self.grok_adapter.summarize_bar(
                    topic=topic,
                    ticks=ticks,
                    start_time=start,
                    end_time=end
                )
            except Exception as e:
                logger.error(f"Failed to generate bar summary: {e}")
        
        return bar
    
    def generate_bars(
        self,
        topic: str,
        resolution: str = DEFAULT_RESOLUTION,
        limit: int = 50,
        generate_summaries: bool = True,
        end_time: Optional[datetime] = None
    ) -> List[Bar]:
        """
        Generate multiple bars at the specified resolution.
        
        Args:
            topic: Topic name
            resolution: Time resolution (e.g., "15s", "1m", "5m")
            limit: Maximum number of bars to generate
            generate_summaries: Whether to generate Grok summaries
            end_time: End time for the most recent bar (default: now)
        
        Returns:
            List of bars, most recent first
        """
        if resolution not in RESOLUTION_MAP:
            raise ValueError(f"Invalid resolution: {resolution}. Valid: {list(RESOLUTION_MAP.keys())}")
        
        resolution_seconds = RESOLUTION_MAP[resolution]
        
        # Determine time range
        if end_time is None:
            end_time = datetime.now(timezone.utc)
        
        # Floor end_time to resolution boundary
        ts = end_time.timestamp()
        bar_end_ts = int(ts // resolution_seconds) * resolution_seconds
        bar_end = datetime.fromtimestamp(bar_end_ts, tz=timezone.utc)
        
        # Generate bars going backwards
        bars = []
        for i in range(limit):
            bar_start = bar_end - timedelta(seconds=resolution_seconds)
            
            bar = self.generate_bar(
                topic=topic,
                start=bar_start,
                end=bar_end,
                resolution=resolution,
                generate_summary=generate_summaries
            )
            bars.append(bar)
            
            # Move to previous bar
            bar_end = bar_start
        
        return bars  # Already most recent first


class DigestService:
    """
    Service for creating topic digests from bars.
    """

    def __init__(self, grok_adapter: GrokAdapter):
        """
        Initialize the DigestService.
        
        Args:
            grok_adapter: GrokAdapter for generating digests
        """
        self.grok_adapter = grok_adapter

    def create_digest(self, topic: str, bars: List[Bar], lookback_bars: int = 12) -> TopicDigest:
        """
        Create a digest for a topic based on provided bars.
        
        Args:
            topic: Topic to create digest for
            bars: List of Bar objects to summarize
            lookback_bars: Maximum number of bars to include (default: 12)
        
        Returns:
            TopicDigest from Grok
        """
        # Limit bars to lookback count
        bars = bars[:lookback_bars] if bars else []
        
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


def get_bar_boundaries(resolution: str, reference_time: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """
    Get the bar boundaries containing the reference time.
    
    Args:
        resolution: Time resolution (e.g., "15s", "1m")
        reference_time: Reference time (default: now)
    
    Returns:
        Tuple of (bar_start, bar_end)
    """
    resolution_seconds = RESOLUTION_MAP.get(resolution, 60)
    now = reference_time or datetime.now(timezone.utc)
    
    # Floor to resolution boundary
    ts = now.timestamp()
    bar_start_ts = int(ts // resolution_seconds) * resolution_seconds
    
    bar_start = datetime.fromtimestamp(bar_start_ts, tz=timezone.utc)
    bar_end = bar_start + timedelta(seconds=resolution_seconds)
    
    return bar_start, bar_end


def get_polling_window(min_age_seconds: int = 15) -> tuple[datetime, datetime]:
    """
    Get a time window for polling that's safe for X API.
    
    X API requires end_time to be at least 10 seconds before now.
    This returns a window ending at least min_age_seconds ago.
    
    Args:
        min_age_seconds: Minimum age for end_time (default: 15s)
    
    Returns:
        Tuple of (start, end) for polling
    """
    now = datetime.now(timezone.utc)
    end = now - timedelta(seconds=min_age_seconds)
    start = end - timedelta(seconds=MIN_RESOLUTION_SECONDS)
    
    return start, end


__all__ = [
    "Bar",
    "TickStore",
    "BarGenerator",
    "DigestService",
    "RESOLUTION_MAP",
    "DEFAULT_RESOLUTION",
    "MIN_RESOLUTION_SECONDS",
    "Tick",  # Re-exported from adapter.models
    "get_bar_boundaries",
    "get_polling_window",
]
