"""Unit tests for the XAdapter module."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock

from adapter.x import (
    XAdapter,
    XAdapterError,
    XAuthenticationError,
    XRateLimitError,
    XAPIError,
    Tick
)
from adapter.rate_limiter import RateLimiter, RateLimitConfig


def create_mock_response(status_code=200, json_data=None, headers=None):
    """Helper to create mock response with proper headers."""
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_data or {}
    mock_response.raise_for_status = Mock()
    mock_response.text = ""
    # Use a real dict for headers (not Mock) to avoid int() issues
    mock_response.headers = headers or {}
    return mock_response


class TestXAdapterInit:
    """Test XAdapter initialization."""

    def test_init_with_bearer_token(self):
        """Test initialization with explicit bearer token."""
        adapter = XAdapter(bearer_token="test_token")
        
        assert adapter.bearer_token == "test_token"
        assert adapter.is_configured is True
        assert "Authorization" in adapter.headers
        assert adapter.headers["Authorization"] == "Bearer test_token"

    def test_init_without_token(self):
        """Test initialization without bearer token."""
        with patch.dict("os.environ", {}, clear=True):
            adapter = XAdapter()
            
            assert adapter.bearer_token is None
            assert adapter.is_configured is False

    def test_init_with_env_token(self):
        """Test initialization with token from environment."""
        with patch.dict("os.environ", {"X_BEARER_TOKEN": "env_token"}):
            adapter = XAdapter()
            
            assert adapter.bearer_token == "env_token"
            assert adapter.is_configured is True

    def test_init_with_custom_rate_limiter(self):
        """Test initialization with custom rate limiter."""
        limiter = RateLimiter()
        adapter = XAdapter(bearer_token="test", rate_limiter=limiter)
        
        assert adapter.rate_limiter is limiter

    def test_default_rate_limit_configured(self):
        """Test that default rate limit is configured."""
        adapter = XAdapter(bearer_token="test")
        
        assert "x_search" in adapter.rate_limiter.configs
        config = adapter.rate_limiter.configs["x_search"]
        # Internal rate limit is generous - X API handles actual limiting
        assert config.requests_per_window == 1000
        assert config.window_seconds == 60


class TestXAdapterHelpers:
    """Test XAdapter helper methods."""

    def test_format_time(self):
        """Test datetime formatting for API."""
        adapter = XAdapter(bearer_token="test")
        
        dt = datetime(2024, 6, 15, 12, 30, 45, tzinfo=timezone.utc)
        formatted = adapter._format_time(dt)
        
        assert formatted == "2024-06-15T12:30:45Z"

    def test_get_time_bounds(self):
        """Test time bounds calculation."""
        adapter = XAdapter(bearer_token="test")
        
        start, end = adapter._get_time_bounds(10)
        
        # Both should be valid ISO format strings ending in Z
        assert start.endswith("Z")
        assert end.endswith("Z")
        
        # Parse them back to verify they're valid
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        
        # Difference should be approximately 10 minutes
        diff = end_dt - start_dt
        assert 9 * 60 <= diff.total_seconds() <= 11 * 60

    def test_parse_tweet_to_tick(self):
        """Test parsing raw tweet to Tick object."""
        adapter = XAdapter(bearer_token="test")
        
        tweet = {
            "id": "123456",
            "text": "Test tweet content",
            "author_id": "user123",
            "created_at": "2024-06-15T12:00:00.000Z",
            "public_metrics": {
                "like_count": 10,
                "retweet_count": 5,
                "reply_count": 2,
                "quote_count": 1
            }
        }
        
        users_map = {
            "user123": {"username": "testuser", "name": "Test User"}
        }
        
        tick = adapter._parse_tweet_to_tick(tweet, users_map, topic="$TSLA")
        
        assert tick.id == "123456"
        assert tick.text == "Test tweet content"
        assert tick.author == "testuser"
        assert tick.topic == "$TSLA"
        assert tick.metrics["like_count"] == 10
        assert tick.metrics["retweet_count"] == 5

    def test_parse_tweet_unknown_author(self):
        """Test parsing tweet with unknown author."""
        adapter = XAdapter(bearer_token="test")
        
        tweet = {
            "id": "123",
            "text": "Test",
            "author_id": "unknown_id",
            "created_at": "2024-06-15T12:00:00.000Z"
        }
        
        tick = adapter._parse_tweet_to_tick(tweet, {}, topic="test")
        
        assert tick.author == "unknown"


class TestXAdapterSearchRecent:
    """Test XAdapter.search_recent method."""

    def test_search_not_configured(self):
        """Test search fails when not configured."""
        with patch.dict("os.environ", {}, clear=True):
            adapter = XAdapter()
            
            with pytest.raises(XAuthenticationError):
                adapter.search_recent("test", topic="test")

    @patch("adapter.x.requests.get")
    def test_search_success(self, mock_get):
        """Test successful search returning ticks."""
        mock_response = create_mock_response(
            status_code=200,
            json_data={
                "data": [
                    {
                        "id": "1",
                        "text": "Tweet 1",
                        "author_id": "u1",
                        "created_at": "2024-06-15T12:00:00.000Z",
                        "public_metrics": {"like_count": 10, "retweet_count": 5}
                    },
                    {
                        "id": "2",
                        "text": "Tweet 2",
                        "author_id": "u2",
                        "created_at": "2024-06-15T12:01:00.000Z",
                        "public_metrics": {"like_count": 20, "retweet_count": 10}
                    }
                ],
                "includes": {
                    "users": [
                        {"id": "u1", "username": "user1"},
                        {"id": "u2", "username": "user2"}
                    ]
                }
            },
            headers={"x-rate-limit-remaining": "449", "x-rate-limit-limit": "450"}
        )
        mock_get.return_value = mock_response
        
        adapter = XAdapter(bearer_token="test_token")
        ticks = adapter.search_recent("$TSLA", topic="$TSLA", minutes=10)
        
        assert len(ticks) == 2
        assert all(isinstance(t, Tick) for t in ticks)
        assert ticks[0].id == "1"
        assert ticks[0].author == "user1"
        assert ticks[0].topic == "$TSLA"
        assert ticks[1].id == "2"

    @patch("adapter.x.requests.get")
    def test_search_empty_results(self, mock_get):
        """Test search with no results."""
        mock_response = create_mock_response(
            status_code=200,
            json_data={"meta": {"result_count": 0}},
            headers={"x-rate-limit-remaining": "449", "x-rate-limit-limit": "450"}
        )
        mock_get.return_value = mock_response
        
        adapter = XAdapter(bearer_token="test_token")
        ticks = adapter.search_recent("nonexistent", topic="test")
        
        assert ticks == []

    @patch("adapter.x.requests.get")
    def test_search_auth_error(self, mock_get):
        """Test search with authentication error."""
        mock_response = create_mock_response(status_code=401)
        mock_get.return_value = mock_response
        
        adapter = XAdapter(bearer_token="bad_token")
        
        with pytest.raises(XAuthenticationError):
            adapter.search_recent("test", topic="test")

    @patch("adapter.x.requests.get")
    def test_search_rate_limit_error(self, mock_get):
        """Test search with rate limit error."""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {
            "x-rate-limit-reset": "1718452800",
            "x-rate-limit-remaining": "0",
            "x-rate-limit-limit": "450"
        }
        mock_get.return_value = mock_response
        
        adapter = XAdapter(bearer_token="test_token")
        
        with pytest.raises(XRateLimitError) as exc_info:
            adapter.search_recent("test", topic="test")
        
        # Verify rate limit details are captured
        assert exc_info.value.reset_time == 1718452800
        assert exc_info.value.remaining == 0
        assert exc_info.value.limit == 450

    @patch("adapter.x.requests.get")
    def test_search_api_error(self, mock_get):
        """Test search with generic API error."""
        mock_response = create_mock_response(status_code=500)
        mock_response.text = "Internal Server Error"
        mock_get.return_value = mock_response
        
        adapter = XAdapter(bearer_token="test_token")
        
        with pytest.raises(XAPIError) as exc_info:
            adapter.search_recent("test", topic="test")
        
        assert exc_info.value.status_code == 500

    @patch("adapter.x.requests.get")
    def test_search_timeout(self, mock_get):
        """Test search with timeout."""
        import requests
        mock_get.side_effect = requests.exceptions.Timeout()
        
        adapter = XAdapter(bearer_token="test_token")
        
        with pytest.raises(XAPIError) as exc_info:
            adapter.search_recent("test", topic="test")
        
        assert "timed out" in str(exc_info.value).lower()

    @patch("adapter.x.requests.get")
    def test_search_adds_retweet_filter(self, mock_get):
        """Test that -is:retweet is added to query."""
        mock_response = create_mock_response(
            status_code=200,
            json_data={"data": [], "meta": {"result_count": 0}}
        )
        mock_get.return_value = mock_response
        
        adapter = XAdapter(bearer_token="test_token")
        adapter.search_recent("$TSLA", topic="$TSLA")
        
        call_kwargs = mock_get.call_args[1]
        query = call_kwargs["params"]["query"]
        assert "-is:retweet" in query

    @patch("adapter.x.requests.get")
    def test_search_respects_existing_retweet_filter(self, mock_get):
        """Test that existing -is:retweet is not duplicated."""
        mock_response = create_mock_response(
            status_code=200,
            json_data={"data": [], "meta": {"result_count": 0}}
        )
        mock_get.return_value = mock_response
        
        adapter = XAdapter(bearer_token="test_token")
        adapter.search_recent("$TSLA -is:retweet", topic="$TSLA")
        
        call_kwargs = mock_get.call_args[1]
        query = call_kwargs["params"]["query"]
        assert query.count("-is:retweet") == 1

    @patch("adapter.x.requests.get")
    def test_search_max_results_bounds(self, mock_get):
        """Test that max_results is bounded between 10 and 100."""
        mock_response = create_mock_response(
            status_code=200,
            json_data={"data": [], "meta": {"result_count": 0}}
        )
        mock_get.return_value = mock_response
        
        adapter = XAdapter(bearer_token="test_token")
        
        # Test lower bound
        adapter.search_recent("test", topic="test", max_results=5)
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["params"]["max_results"] == 10
        
        # Test upper bound
        adapter.search_recent("test", topic="test", max_results=200)
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["params"]["max_results"] == 100


class TestXAdapterSearchForBar:
    """Test XAdapter.search_for_bar method."""

    @patch("adapter.x.requests.get")
    def test_search_for_bar_uses_explicit_times(self, mock_get):
        """Test that search_for_bar uses explicit start/end times."""
        mock_response = create_mock_response(
            status_code=200,
            json_data={
                "data": [
                    {
                        "id": "1",
                        "text": "Test",
                        "author_id": "u1",
                        "created_at": "2024-06-15T12:00:00.000Z"
                    }
                ],
                "includes": {"users": [{"id": "u1", "username": "user1"}]}
            },
            headers={"x-rate-limit-remaining": "449", "x-rate-limit-limit": "450"}
        )
        mock_get.return_value = mock_response
        
        adapter = XAdapter(bearer_token="test_token")
        
        start = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        end = datetime(2024, 6, 15, 12, 5, 0, tzinfo=timezone.utc)
        
        ticks = adapter.search_for_bar("$TSLA", "$TSLA", start, end)
        
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["params"]["start_time"] == "2024-06-15T12:00:00Z"
        assert call_kwargs["params"]["end_time"] == "2024-06-15T12:05:00Z"
        assert len(ticks) == 1


class TestXAdapterGetTweetCounts:
    """Test XAdapter.get_tweet_counts method."""

    def test_counts_not_configured(self):
        """Test counts fails when not configured."""
        with patch.dict("os.environ", {}, clear=True):
            adapter = XAdapter()
            
            with pytest.raises(XAuthenticationError):
                adapter.get_tweet_counts("test")

    @patch("adapter.x.requests.get")
    def test_counts_success(self, mock_get):
        """Test successful counts retrieval."""
        mock_response = create_mock_response(
            status_code=200,
            json_data={
                "data": [
                    {"start": "2024-06-15T12:00:00.000Z", "end": "2024-06-15T12:01:00.000Z", "tweet_count": 10},
                    {"start": "2024-06-15T12:01:00.000Z", "end": "2024-06-15T12:02:00.000Z", "tweet_count": 15}
                ]
            }
        )
        mock_get.return_value = mock_response
        
        adapter = XAdapter(bearer_token="test_token")
        counts = adapter.get_tweet_counts("$TSLA", granularity="minute", minutes=60)
        
        assert len(counts) == 2
        assert counts[0]["tweet_count"] == 10
        assert counts[1]["tweet_count"] == 15

    @patch("adapter.x.requests.get")
    def test_counts_empty(self, mock_get):
        """Test counts with no data."""
        mock_response = create_mock_response(status_code=200, json_data={})
        mock_get.return_value = mock_response
        
        adapter = XAdapter(bearer_token="test_token")
        counts = adapter.get_tweet_counts("nonexistent")
        
        assert counts == []


class TestTickModel:
    """Test the Tick model from adapter.x"""

    def test_tick_creation(self):
        """Test creating a Tick object."""
        now = datetime.now(timezone.utc)
        tick = Tick(
            id="123",
            author="testuser",
            text="Test tweet",
            timestamp=now,
            metrics={"like_count": 10},
            topic="$TSLA"
        )
        
        assert tick.id == "123"
        assert tick.author == "testuser"
        assert tick.topic == "$TSLA"

    def test_tick_default_metrics(self):
        """Test Tick with default empty metrics."""
        tick = Tick(
            id="123",
            author="user",
            text="Test",
            timestamp=datetime.now(timezone.utc),
            topic="test"
        )
        
        assert tick.metrics == {}

    def test_tick_serialization(self):
        """Test Tick JSON serialization."""
        now = datetime.now(timezone.utc)
        tick = Tick(
            id="123",
            author="user",
            text="Test",
            timestamp=now,
            metrics={"like_count": 10},
            topic="$TSLA"
        )
        
        data = tick.model_dump(mode="json")
        
        assert data["id"] == "123"
        assert data["author"] == "user"
        assert data["metrics"]["like_count"] == 10

