"""Unit tests for the simplified Aggregator module."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock

from aggregator import (
    Tick, Bar, BarGenerator, TickStore, DigestService,
    RESOLUTION_MAP, get_bar_boundaries, get_polling_window
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
            sentiment=0.8,  # Positive
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
        assert bar_dict["sentiment"] == 0.8
        assert bar_dict["key_themes"] == ["tech", "ai"]


class TestBarGenerator:
    """Test the BarGenerator class."""

    def test_generator_init(self):
        """Test initializing the bar generator."""
        mock_grok = Mock()
        tick_store = TickStore()
        generator = BarGenerator(grok_adapter=mock_grok, tick_store=tick_store)
        
        assert generator.grok_adapter == mock_grok
        assert generator.tick_store == tick_store

    def test_generate_bar_with_ticks(self):
        """Test generating a bar with ticks in the store."""
        mock_grok = Mock()
        mock_summary = BarSummary(
            summary="Test summary",
            key_themes=["tech"],
            sentiment=0.75,  # Positive
            post_count=2,
            engagement_level="high"
        )
        mock_grok.summarize_bar.return_value = mock_summary
        
        tick_store = TickStore()
        generator = BarGenerator(grok_adapter=mock_grok, tick_store=tick_store)
        
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=5)
        end = now
        
        # Add ticks to the store
        ticks = [
            create_tick("tick1", topic="$TSLA", timestamp=start + timedelta(minutes=1)),
            create_tick("tick2", topic="$TSLA", timestamp=start + timedelta(minutes=2)),
        ]
        tick_store.add_ticks("$TSLA", ticks)
        
        bar = generator.generate_bar("$TSLA", start, end, "5m")
        
        assert bar.topic == "$TSLA"
        assert bar.post_count == 2
        assert bar.total_likes == 20  # 10 * 2 ticks
        assert bar.total_retweets == 10  # 5 * 2 ticks
        assert bar.summary == mock_summary
        assert len(bar.sample_post_ids) == 2
        mock_grok.summarize_bar.assert_called_once()

    def test_generate_bar_empty(self):
        """Test generating a bar with no ticks."""
        mock_grok = Mock()
        tick_store = TickStore()
        generator = BarGenerator(grok_adapter=mock_grok, tick_store=tick_store)
        
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=5)
        end = now
        
        bar = generator.generate_bar("$TSLA", start, end, "5m")
        
        assert bar.post_count == 0
        assert bar.summary is None
        mock_grok.summarize_bar.assert_not_called()

    def test_generate_bar_without_summary(self):
        """Test generating a bar without generating summary."""
        mock_grok = Mock()
        tick_store = TickStore()
        generator = BarGenerator(grok_adapter=mock_grok, tick_store=tick_store)
        
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=5)
        end = now
        
        # Add a tick to the store
        tick_store.add_ticks("$TSLA", [create_tick("tick1", topic="$TSLA", timestamp=start + timedelta(minutes=1))])
        
        bar = generator.generate_bar(
            "$TSLA", start, end, "5m",
            generate_summary=False
        )
        
        assert bar.post_count == 1
        assert bar.summary is None
        mock_grok.summarize_bar.assert_not_called()

    def test_generate_bars(self):
        """Test generating multiple bars for a topic."""
        mock_grok = Mock()
        mock_grok.summarize_bar.return_value = BarSummary(
            summary="Test", key_themes=[], sentiment=0.5,
            post_count=1, engagement_level="low"
        )
        
        tick_store = TickStore()
        generator = BarGenerator(grok_adapter=mock_grok, tick_store=tick_store)
        
        now = datetime.now(timezone.utc)
        
        # Add ticks at different times across multiple bars
        for i in range(3):
            ts = now - timedelta(minutes=(i+1)*5 - 2)  # Place in the middle of each bar
            tick_store.add_ticks("$TSLA", [create_tick(f"tick{i}", topic="$TSLA", timestamp=ts)])
        
        bars = generator.generate_bars("$TSLA", resolution="5m", limit=10, generate_summaries=False)
        
        # Should have bars (number depends on time window)
        assert len(bars) > 0
        # Should be sorted by start time descending (most recent first)
        for i in range(len(bars) - 1):
            assert bars[i].start >= bars[i+1].start

    def test_generate_bars_with_limit(self):
        """Test limiting the number of bars generated."""
        mock_grok = Mock()
        tick_store = TickStore()
        generator = BarGenerator(grok_adapter=mock_grok, tick_store=tick_store)
        
        bars = generator.generate_bars("$TSLA", resolution="5m", limit=3, generate_summaries=False)
        
        assert len(bars) == 3

    def test_generate_bars_empty_topic(self):
        """Test generating bars for topic with no ticks."""
        mock_grok = Mock()
        tick_store = TickStore()
        generator = BarGenerator(grok_adapter=mock_grok, tick_store=tick_store)
        
        bars = generator.generate_bars("$TSLA", resolution="5m", limit=3, generate_summaries=False)
        
        # Should still return bars (empty bars)
        assert len(bars) == 3
        for bar in bars:
            assert bar.post_count == 0

    def test_tick_store_clear_topic(self):
        """Test clearing all ticks for a topic."""
        tick_store = TickStore()
        
        now = datetime.now(timezone.utc)
        ticks = [create_tick("tick1", topic="$TSLA", timestamp=now)]
        tick_store.add_ticks("$TSLA", ticks)
        
        assert tick_store.get_tick_count("$TSLA") == 1
        
        tick_store.clear_topic("$TSLA")
        
        assert tick_store.get_tick_count("$TSLA") == 0

    def test_multiple_topics(self):
        """Test ticks for multiple topics."""
        tick_store = TickStore()
        
        now = datetime.now(timezone.utc)
        
        # Add ticks for different topics
        tick_store.add_ticks("$TSLA", [create_tick("tick1", topic="$TSLA", timestamp=now)])
        tick_store.add_ticks("$AAPL", [create_tick("tick2", topic="$AAPL", timestamp=now)])
        
        assert tick_store.get_tick_count("$TSLA") == 1
        assert tick_store.get_tick_count("$AAPL") == 1

    def test_sample_posts_limited_to_5(self):
        """Test that sample posts are limited to 5."""
        mock_grok = Mock()
        tick_store = TickStore()
        generator = BarGenerator(grok_adapter=mock_grok, tick_store=tick_store)
        
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=5)
        end = now
        
        # Add 10 ticks
        ticks = [create_tick(f"tick{i}", topic="$TSLA", timestamp=start + timedelta(minutes=i*0.4)) for i in range(10)]
        tick_store.add_ticks("$TSLA", ticks)
        
        bar = generator.generate_bar("$TSLA", start, end, "5m", generate_summary=False)
        
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
        
        # Create some bars manually
        now = datetime.now(timezone.utc)
        bars = []
        for i in range(3):
            start = now - timedelta(minutes=(i+1)*5)
            end = start + timedelta(minutes=5)
            bar = Bar(
                topic="$TSLA",
                resolution="5m",
                start=start,
                end=end,
                post_count=5,
                total_likes=100,
                summary=BarSummary(
                    summary="Bar summary", key_themes=["tech"],
                    sentiment=0.8, post_count=5, engagement_level="high"
                )
            )
            bars.append(bar)
        
        service = DigestService(grok_adapter=mock_grok)
        
        # Pass bars directly to create_digest
        digest = service.create_digest("$TSLA", bars=bars)
        
        assert digest == mock_digest
        mock_grok.create_topic_digest.assert_called_once()

    def test_create_digest_grok_failure(self):
        """Test handling GrokAdapter failure."""
        mock_grok = Mock()
        mock_grok.create_topic_digest.side_effect = RuntimeError("API Error")
        
        # Create a bar manually
        now = datetime.now(timezone.utc)
        bar = Bar(
            topic="$TSLA",
            resolution="5m",
            start=now - timedelta(minutes=5),
            end=now,
            post_count=1
        )
        
        service = DigestService(grok_adapter=mock_grok)
        
        with pytest.raises(RuntimeError) as exc_info:
            service.create_digest("$TSLA", bars=[bar])
        
        assert "Failed to generate digest" in str(exc_info.value)


class TestResolutionHelpers:
    """Test resolution helper functions."""

    def test_resolution_map_values(self):
        """Test resolution map values."""
        assert RESOLUTION_MAP["15s"] == 15
        assert RESOLUTION_MAP["30s"] == 30
        assert RESOLUTION_MAP["1m"] == 60
        assert RESOLUTION_MAP["5m"] == 300
        assert RESOLUTION_MAP["15m"] == 900
        assert RESOLUTION_MAP["30m"] == 1800
        assert RESOLUTION_MAP["1h"] == 3600

    def test_get_bar_boundaries(self):
        """Test getting bar boundaries for a reference time."""
        reference = datetime(2024, 1, 15, 12, 7, 30, tzinfo=timezone.utc)
        start, end = get_bar_boundaries("5m", reference)
        
        # Should floor to 12:05 - 12:10 for 5m resolution
        assert start == datetime(2024, 1, 15, 12, 5, 0, tzinfo=timezone.utc)
        assert end == datetime(2024, 1, 15, 12, 10, 0, tzinfo=timezone.utc)
        
        diff = end - start
        assert diff.total_seconds() == 300

    def test_get_polling_window(self):
        """Test getting a safe polling window for X API."""
        start, end = get_polling_window(min_age_seconds=15)
        
        # Window should be MIN_RESOLUTION_SECONDS long
        diff = end - start
        assert diff.total_seconds() == 15  # MIN_RESOLUTION_SECONDS
        
        # End should be at least 15 seconds ago
        now = datetime.now(timezone.utc)
        assert (now - end).total_seconds() >= 15
