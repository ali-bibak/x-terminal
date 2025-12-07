"""Unit tests for GrokAdapter."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from adapter.grok import (
    GrokAdapter,
    BarSummary,
    TopicDigest
)
from adapter.grok.mocks import (
    mock_bar_summary,
    mock_topic_digest,
    mock_intel_summary,
    mock_fact_check_report,
    mock_digest_overview
)
from adapter.x import Tick
from adapter.rate_limiter import RateLimiter, RateLimitConfig


class TestRateLimiter:
    """Test the RateLimiter class."""

    def test_rate_limiter_init(self):
        limiter = RateLimiter()
        assert len(limiter.configs) == 0
        assert len(limiter.sliding_windows) == 0

    def test_rate_limiter_configure(self):
        limiter = RateLimiter()
        config = RateLimitConfig(requests_per_window=10, window_seconds=60, strategy="sliding_window")
        limiter.configure_limit("test", config)

        assert "test" in limiter.configs
        assert limiter.configs["test"] == config

    def test_rate_limiter_no_wait_needed(self):
        limiter = RateLimiter()
        limiter.configure_limit("test", RateLimitConfig(10, 60, "sliding_window"))

        # Should not wait when under limit
        limiter.wait_if_needed("test")
        assert len(limiter.sliding_windows["test"]) == 1

    @patch('time.sleep')
    @patch('time.time')
    def test_rate_limiter_with_wait(self, mock_time, mock_sleep):
        limiter = RateLimiter()
        limiter.configure_limit("test", RateLimitConfig(2, 60, "sliding_window"))

        # Simulate time progression - all calls in same second
        mock_time.return_value = 1000

        limiter.wait_if_needed("test")  # First call
        limiter.wait_if_needed("test")  # Second call (at limit)
        limiter.wait_if_needed("test")  # Third call (should wait)

        # Should have called sleep once
        mock_sleep.assert_called_once()
        assert mock_sleep.call_args[0][0] > 0  # Wait time should be positive

    def test_token_bucket_strategy(self):
        limiter = RateLimiter()
        limiter.configure_limit("test", RateLimitConfig(10, 60, "token_bucket"))

        # Should be able to make calls up to the limit without waiting
        for i in range(10):
            limiter.wait_if_needed("test")

        # Bucket should be empty
        assert limiter.token_buckets["test"] == 0


class TestGrokAdapter:
    """Test the GrokAdapter class."""

    def test_adapter_init_without_client(self):
        """Test initialization without API client."""
        limiter = RateLimiter()
        with patch.dict('os.environ', {}, clear=True):
            adapter = GrokAdapter(limiter)
            assert adapter.api_key is None
            assert adapter._client is None
            assert not adapter.is_live
            assert adapter.rate_limiter == limiter

    def test_adapter_init_with_client(self):
        """Test initialization with API client."""
        limiter = RateLimiter()
        with patch('adapter.grok.Client') as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            with patch.dict('os.environ', {'XAI_API_KEY': 'test_key'}):
                adapter = GrokAdapter(limiter)
                assert adapter.api_key == 'test_key'
                assert adapter._client == mock_client
                assert adapter.is_live
                assert adapter.rate_limiter == limiter
                mock_client_class.assert_called_once_with(api_key='test_key')

    def test_mock_bar_summary_empty_posts(self):
        """Test mock bar summary with no posts."""
        start_time = datetime.now(timezone.utc)
        end_time = start_time + timedelta(minutes=5)

        summary = mock_bar_summary("test_topic", [], start_time, end_time)

        assert isinstance(summary, BarSummary)
        assert summary.post_count == 0
        assert "No posts" in summary.summary
        assert summary.highlight_posts is None

    def test_mock_bar_summary_with_posts(self):
        """Test mock bar summary with posts."""
        ticks = [
            Tick(
                id="tick1",
                author="user1",
                text="Great news!",
                timestamp=datetime.now(timezone.utc),
                permalink="https://twitter.com/user1/status/tick1",
                metrics={"retweet_count": 10, "like_count": 20},
                topic="test_topic"
            ),
            Tick(
                id="tick2",
                author="user2",
                text="Interesting development",
                timestamp=datetime.now(timezone.utc),
                permalink="https://twitter.com/user2/status/tick2",
                metrics={"retweet_count": 5, "like_count": 15},
                topic="test_topic"
            )
        ]
        start_time = datetime.now(timezone.utc)
        end_time = start_time + timedelta(minutes=5)

        summary = mock_bar_summary("test_topic", ticks, start_time, end_time)

        assert isinstance(summary, BarSummary)
        assert summary.post_count == 2
        assert summary.summary is not None
        assert summary.sentiment in ["positive", "negative", "neutral", "mixed"]
        assert summary.engagement_level in ["low", "medium", "high"]
        assert summary.highlight_posts is not None
        assert len(summary.highlight_posts) <= 2
        assert all(pid in ["tick1", "tick2"] for pid in summary.highlight_posts)

    def test_mock_topic_digest_no_bars(self):
        """Test mock topic digest with no bars."""

        digest = mock_topic_digest("test_topic", [], 1)

        assert isinstance(digest, TopicDigest)
        assert digest.topic == "test_topic"
        assert "No significant activity" in digest.overall_summary

    def test_mock_topic_digest_with_bars(self):
        """Test mock topic digest with bars data."""
        bars_data = [
            {"start": "10:00", "summary": "Initial discussion", "post_count": 5},
            {"start": "10:05", "summary": "Growing momentum", "post_count": 12}
        ]

        digest = mock_topic_digest("test_topic", bars_data, 1)

        assert isinstance(digest, TopicDigest)
        assert digest.topic == "test_topic"
        assert digest.overall_summary is not None
        assert len(digest.key_developments) > 0
        assert len(digest.recommendations) > 0

    def test_summarize_bar_empty_posts(self):
        """Test summarize_bar with empty posts list."""
        adapter = GrokAdapter()
        start_time = datetime.now(timezone.utc)
        end_time = start_time + timedelta(minutes=5)

        summary = adapter.summarize_bar("test_topic", [], start_time, end_time)

        assert isinstance(summary, BarSummary)
        assert summary.post_count == 0
        assert "No posts" in summary.summary

    @patch('adapter.grok.Client')
    def test_summarize_bar_with_api_call(self, mock_client_class):
        """Test summarize_bar when API client is available."""
        mock_client = Mock()
        mock_chat = Mock()
        mock_client.chat.create.return_value = mock_chat

        # Mock the parse method to return a BarSummary
        expected_summary = BarSummary(
            summary="Test summary",
            key_themes=["theme1", "theme2"],
            sentiment="positive",
            post_count=5,
            engagement_level="high"
        )
        mock_chat.parse.return_value = (None, expected_summary)

        mock_client_class.return_value = mock_client

        with patch.dict('os.environ', {'XAI_API_KEY': 'test_key'}):
            adapter = GrokAdapter()
            posts = [{"author": "user1", "text": "Test post"}]
            start_time = datetime.now(timezone.utc)
            end_time = start_time + timedelta(minutes=5)

            result = adapter.summarize_bar("test_topic", posts, start_time, end_time)

            assert isinstance(result, BarSummary)
            assert result.summary == "Test summary"
            # Should override post_count to match actual data
            assert result.post_count == 1

    @patch('adapter.grok.Client')
    def test_create_topic_digest_with_api_call(self, mock_client_class):
        """Test create_topic_digest when API client is available."""
        mock_client = Mock()
        mock_chat = Mock()
        mock_client.chat.create.return_value = mock_chat

        expected_digest = TopicDigest(
            topic="test_topic",
            generated_at=datetime.now(timezone.utc),
            time_range="Last 1 hour(s)",
            overall_summary="Test summary",
            key_developments=["dev1", "dev2"],
            trending_elements=["trend1"],
            sentiment_trend="improving",
            recommendations=["rec1", "rec2"]
        )
        mock_chat.parse.return_value = (None, expected_digest)

        mock_client_class.return_value = mock_client

        with patch.dict('os.environ', {'XAI_API_KEY': 'test_key'}):
            adapter = GrokAdapter()
            bars_data = [{"start": "10:00", "summary": "test", "post_count": 5}]

            result = adapter.create_topic_digest("test_topic", bars_data, 1)

            assert isinstance(result, TopicDigest)
            assert result.topic == "test_topic"
            assert result.overall_summary == "Test summary"
