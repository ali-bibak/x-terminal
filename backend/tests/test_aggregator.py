"""Unit tests for the simplified Aggregator module."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock

from aggregator import (
    Tick, Bar, BarAggregator, DigestService,
    RESOLUTION_MAP, get_bar_window, get_previous_bar_window
)
from adapter.grok import BarSummary, TopicDigest


def create_tick(
    tick_id: str,
    topic: str = "test_topic",
    timestamp: datetime = None,
    author: str = "testuser",
    text: str = "Test tweet content",
    metrics: dict = None
) -> Tick:
    """Helper function to create test ticks."""
    return Tick(
        id=tick_id,
        author=author,
        text=text,
        timestamp=timestamp or datetime.now(timezone.utc),
        metrics=metrics or {"like_count": 10, "retweet_count": 5, "reply_count": 2, "quote_count": 1},
        topic=topic
    )


class TestTick:
    """Test the Tick model."""

    def test_tick_creation(self):
        """Test creating a tick."""
        now = datetime.now(timezone.utc)
        tick = Tick(
            id="123",
            author="user1",
            text="Hello world",
            timestamp=now,
            metrics={"like_count": 10},
            topic="$TSLA"
        )
        
        assert tick.id == "123"
        assert tick.author == "user1"
        assert tick.topic == "$TSLA"


class TestBar:
    """Test the Bar model."""

    def test_bar_creation(self):
        """Test creating a basic bar."""
        now = datetime.now(timezone.utc)
        bar = Bar(
            topic="test_topic",
            resolution="5m",
            start=now,
            end=now + timedelta(minutes=5),
        )
        
        assert bar.topic == "test_topic"
        assert bar.resolution == "5m"
        assert bar.post_count == 0
        assert bar.summary is None

    def test_bar_to_dict(self):
        """Test converting bar to dictionary."""
        now = datetime.now(timezone.utc)
        bar = Bar(
            topic="test_topic",
            resolution="5m",
            start=now,
            end=now + timedelta(minutes=5),
            post_count=10,
            total_likes=100,
            total_retweets=50,
        )
        
        bar_dict = bar.to_dict()
        
        assert bar_dict["topic"] == "test_topic"
        assert bar_dict["post_count"] == 10
        assert bar_dict["total_likes"] == 100
        assert bar_dict["summary"] is None

    def test_bar_with_summary(self):
        """Test bar with attached summary."""
        now = datetime.now(timezone.utc)
        summary = BarSummary(
            summary="Test summary",
            key_themes=["tech", "ai"],
            sentiment="positive",
            post_count=5,
            engagement_level="high",
            highlight_posts=["post1", "post2"]
        )
        
        bar = Bar(
            topic="test_topic",
            resolution="5m",
            start=now,
            end=now + timedelta(minutes=5),
            summary=summary
        )
        
        bar_dict = bar.to_dict()
        assert bar_dict["summary"] == "Test summary"
        assert bar_dict["sentiment"] == "positive"
        assert bar_dict["key_themes"] == ["tech", "ai"]


class TestBarAggregator:
    """Test the BarAggregator class."""

    def test_aggregator_init(self):
        """Test initializing the aggregator."""
        mock_grok = Mock()
        aggregator = BarAggregator(grok_adapter=mock_grok)
        
        assert aggregator.default_resolution == "5m"
        assert aggregator.grok_adapter == mock_grok

    def test_create_bar_with_ticks(self):
        """Test creating a bar with ticks."""
        mock_grok = Mock()
        mock_summary = BarSummary(
            summary="Test summary",
            key_themes=["tech"],
            sentiment="positive",
            post_count=2,
            engagement_level="high"
        )
        mock_grok.summarize_bar.return_value = mock_summary
        
        aggregator = BarAggregator(grok_adapter=mock_grok)
        
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=5)
        end = now
        
        ticks = [
            create_tick("tick1", topic="$TSLA", timestamp=start + timedelta(minutes=1)),
            create_tick("tick2", topic="$TSLA", timestamp=start + timedelta(minutes=2)),
        ]
        
        bar = aggregator.create_bar("$TSLA", ticks, start, end)
        
        assert bar.topic == "$TSLA"
        assert bar.post_count == 2
        assert bar.total_likes == 20  # 10 * 2 ticks
        assert bar.total_retweets == 10  # 5 * 2 ticks
        assert bar.summary == mock_summary
        assert len(bar.sample_post_ids) == 2
        mock_grok.summarize_bar.assert_called_once()

    def test_create_bar_empty(self):
        """Test creating a bar with no ticks."""
        mock_grok = Mock()
        aggregator = BarAggregator(grok_adapter=mock_grok)
        
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=5)
        end = now
        
        bar = aggregator.create_bar("$TSLA", [], start, end)
        
        assert bar.post_count == 0
        assert bar.summary is None
        mock_grok.summarize_bar.assert_not_called()

    def test_create_bar_without_summary(self):
        """Test creating a bar without generating summary."""
        mock_grok = Mock()
        aggregator = BarAggregator(grok_adapter=mock_grok)
        
        now = datetime.now(timezone.utc)
        ticks = [create_tick("tick1", topic="$TSLA")]
        
        bar = aggregator.create_bar(
            "$TSLA", ticks,
            start=now - timedelta(minutes=5),
            end=now,
            generate_summary=False
        )
        
        assert bar.post_count == 1
        assert bar.summary is None
        mock_grok.summarize_bar.assert_not_called()

    def test_get_bars(self):
        """Test retrieving bars for a topic."""
        mock_grok = Mock()
        mock_grok.summarize_bar.return_value = BarSummary(
            summary="Test", key_themes=[], sentiment="neutral",
            post_count=1, engagement_level="low"
        )
        
        aggregator = BarAggregator(grok_adapter=mock_grok)
        
        now = datetime.now(timezone.utc)
        
        # Create bars at different times
        for i in range(3):
            start = now - timedelta(minutes=(i+1)*5)
            end = start + timedelta(minutes=5)
            ticks = [create_tick(f"tick{i}", topic="$TSLA", timestamp=start)]
            aggregator.create_bar("$TSLA", ticks, start, end)
        
        bars = aggregator.get_bars("$TSLA", limit=10)
        
        assert len(bars) == 3
        # Should be sorted by start time descending
        assert bars[0].start >= bars[1].start >= bars[2].start

    def test_get_bars_with_limit(self):
        """Test limiting the number of bars returned."""
        mock_grok = Mock()
        mock_grok.summarize_bar.return_value = BarSummary(
            summary="Test", key_themes=[], sentiment="neutral",
            post_count=1, engagement_level="low"
        )
        
        aggregator = BarAggregator(grok_adapter=mock_grok)
        
        now = datetime.now(timezone.utc)
        
        # Create 5 bars
        for i in range(5):
            start = now - timedelta(minutes=(i+1)*5)
            end = start + timedelta(minutes=5)
            ticks = [create_tick(f"tick{i}", topic="$TSLA", timestamp=start)]
            aggregator.create_bar("$TSLA", ticks, start, end)
        
        bars = aggregator.get_bars("$TSLA", limit=3)
        
        assert len(bars) == 3

    def test_get_latest_bar(self):
        """Test getting the most recent bar."""
        mock_grok = Mock()
        mock_grok.summarize_bar.return_value = BarSummary(
            summary="Test", key_themes=[], sentiment="neutral",
            post_count=1, engagement_level="low"
        )
        
        aggregator = BarAggregator(grok_adapter=mock_grok)
        
        now = datetime.now(timezone.utc)
        
        # Create bars at different times
        for i in range(3):
            start = now - timedelta(minutes=(i+1)*5)
            end = start + timedelta(minutes=5)
            ticks = [create_tick(f"tick{i}", topic="$TSLA", timestamp=start)]
            aggregator.create_bar("$TSLA", ticks, start, end)
        
        latest = aggregator.get_latest_bar("$TSLA")
        
        assert latest is not None
        assert latest.sample_post_ids == ["tick0"]

    def test_get_latest_bar_no_bars(self):
        """Test getting latest bar when none exist."""
        mock_grok = Mock()
        aggregator = BarAggregator(grok_adapter=mock_grok)
        
        latest = aggregator.get_latest_bar("$TSLA")
        
        assert latest is None

    def test_clear_topic(self):
        """Test clearing all bars for a topic."""
        mock_grok = Mock()
        mock_grok.summarize_bar.return_value = BarSummary(
            summary="Test", key_themes=[], sentiment="neutral",
            post_count=1, engagement_level="low"
        )
        
        aggregator = BarAggregator(grok_adapter=mock_grok)
        
        now = datetime.now(timezone.utc)
        ticks = [create_tick("tick1", topic="$TSLA")]
        aggregator.create_bar("$TSLA", ticks, now - timedelta(minutes=5), now)
        
        assert len(aggregator.get_bars("$TSLA")) == 1
        
        aggregator.clear_topic("$TSLA")
        
        assert len(aggregator.get_bars("$TSLA")) == 0

    def test_multiple_topics(self):
        """Test bars for multiple topics."""
        mock_grok = Mock()
        mock_grok.summarize_bar.return_value = BarSummary(
            summary="Test", key_themes=[], sentiment="neutral",
            post_count=1, engagement_level="low"
        )
        
        aggregator = BarAggregator(grok_adapter=mock_grok)
        
        now = datetime.now(timezone.utc)
        
        # Create bars for different topics
        for topic in ["$TSLA", "$AAPL"]:
            ticks = [create_tick("tick", topic=topic)]
            aggregator.create_bar(topic, ticks, now - timedelta(minutes=5), now)
        
        assert len(aggregator.get_bars("$TSLA")) == 1
        assert len(aggregator.get_bars("$AAPL")) == 1

    def test_sample_posts_limited_to_5(self):
        """Test that sample posts are limited to 5."""
        mock_grok = Mock()
        mock_grok.summarize_bar.return_value = BarSummary(
            summary="Test", key_themes=[], sentiment="neutral",
            post_count=10, engagement_level="high"
        )
        
        aggregator = BarAggregator(grok_adapter=mock_grok)
        
        now = datetime.now(timezone.utc)
        ticks = [create_tick(f"tick{i}", topic="$TSLA") for i in range(10)]
        
        bar = aggregator.create_bar("$TSLA", ticks, now - timedelta(minutes=5), now)
        
        assert len(bar.sample_post_ids) == 5


class TestDigestService:
    """Test the DigestService class."""

    def test_digest_service_init(self):
        """Test initializing the DigestService."""
        mock_grok = Mock()
        
        service = DigestService(grok_adapter=mock_grok)
        
        assert service.grok_adapter == mock_grok

    def test_create_digest_no_bars(self):
        """Test creating digest when no bars exist."""
        mock_grok = Mock()
        
        service = DigestService(grok_adapter=mock_grok)
        
        digest = service.create_digest("$TSLA", bars=[])
        
        assert digest.topic == "$TSLA"
        assert "No recent activity" in digest.overall_summary

    def test_create_digest_with_bars(self):
        """Test creating digest with existing bars."""
        mock_grok = Mock()
        mock_summary = BarSummary(
            summary="Bar summary", key_themes=["tech"],
            sentiment="positive", post_count=5, engagement_level="high"
        )
        mock_grok.summarize_bar.return_value = mock_summary
        
        mock_digest = TopicDigest(
            topic="$TSLA",
            generated_at=datetime.now(timezone.utc),
            time_range="Last 1 hour(s)",
            overall_summary="Test digest",
            key_developments=["dev1", "dev2"],
            trending_elements=["trend1"],
            sentiment_trend="improving",
            recommendations=["rec1"]
        )
        mock_grok.create_topic_digest.return_value = mock_digest
        
        aggregator = BarAggregator(grok_adapter=mock_grok)
        
        # Create some bars
        now = datetime.now(timezone.utc)
        bars = []
        for i in range(3):
            start = now - timedelta(minutes=(i+1)*5)
            end = start + timedelta(minutes=5)
            ticks = [create_tick(f"tick{i}", topic="$TSLA", timestamp=start)]
            bar = aggregator.create_bar("$TSLA", ticks, start, end)
            bars.append(bar)
        
        service = DigestService(grok_adapter=mock_grok)
        
        # Pass bars directly to create_digest
        digest = service.create_digest("$TSLA", bars=bars)
        
        assert digest == mock_digest
        mock_grok.create_topic_digest.assert_called_once()

    def test_create_digest_grok_failure(self):
        """Test handling GrokAdapter failure."""
        mock_grok = Mock()
        mock_summary = BarSummary(
            summary="Test", key_themes=[], sentiment="neutral",
            post_count=1, engagement_level="low"
        )
        mock_grok.summarize_bar.return_value = mock_summary
        mock_grok.create_topic_digest.side_effect = RuntimeError("API Error")
        
        aggregator = BarAggregator(grok_adapter=mock_grok)
        
        now = datetime.now(timezone.utc)
        ticks = [create_tick("tick1", topic="$TSLA")]
        bar = aggregator.create_bar("$TSLA", ticks, now - timedelta(minutes=5), now)
        
        service = DigestService(grok_adapter=mock_grok)
        
        with pytest.raises(RuntimeError) as exc_info:
            service.create_digest("$TSLA", bars=[bar])
        
        assert "Failed to generate digest" in str(exc_info.value)


class TestResolutionHelpers:
    """Test resolution helper functions."""

    def test_resolution_map_values(self):
        """Test resolution map values."""
        assert RESOLUTION_MAP["1m"] == 60
        assert RESOLUTION_MAP["5m"] == 300
        assert RESOLUTION_MAP["10m"] == 600
        assert RESOLUTION_MAP["15m"] == 900
        assert RESOLUTION_MAP["30m"] == 1800
        assert RESOLUTION_MAP["1h"] == 3600

    def test_get_bar_window(self):
        """Test getting current bar window."""
        start, end = get_bar_window("5m")
        
        diff = end - start
        assert diff.total_seconds() == 300
        assert start.tzinfo == timezone.utc

    def test_get_previous_bar_window(self):
        """Test getting previous bar window."""
        prev_start, prev_end = get_previous_bar_window("5m")
        curr_start, curr_end = get_bar_window("5m")
        
        # Previous end should equal current start
        assert prev_end == curr_start
        
        diff = prev_end - prev_start
        assert diff.total_seconds() == 300
