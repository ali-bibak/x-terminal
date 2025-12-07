"""
End-to-end API tests with mock data.

Tests the full flow: API → TopicManager → Adapters (mocked) → Response
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient

from main import app
from adapter.models import Tick
from adapter.grok import BarSummary, TopicDigest
from core import TopicManager, TickPoller, Topic, TopicStatus
from aggregator import Bar, BarAggregator


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_x_adapter():
    """Create a mock X adapter that returns test data."""
    adapter = Mock()
    adapter.is_configured = True
    adapter.search_for_bar = Mock(return_value=[])
    adapter.search_recent = Mock(return_value=[])
    adapter.get_rate_limit_status = Mock(return_value={
        "limit": 450,
        "remaining": 449,
        "reset_time": None
    })
    return adapter


@pytest.fixture
def mock_grok_adapter():
    """Create a mock Grok adapter."""
    adapter = Mock()
    adapter.is_live = True
    adapter.summarize_bar = Mock(return_value=BarSummary(
        summary="Test summary for the bar",
        key_themes=["theme1", "theme2"],
        sentiment="positive",
        post_count=5,
        engagement_level="high",
        highlight_posts=["post1", "post2"]
    ))
    adapter.create_topic_digest = Mock(return_value=TopicDigest(
        topic="$TSLA",
        generated_at=datetime.now(timezone.utc),
        time_range="Last 1 hour",
        overall_summary="Tesla had significant discussion today",
        key_developments=["Earnings beat", "New product announced"],
        trending_elements=["#Tesla", "@elonmusk"],
        sentiment_trend="improving",
        recommendations=["Monitor earnings reactions"]
    ))
    return adapter


@pytest.fixture
def sample_ticks():
    """Generate sample ticks for testing."""
    now = datetime.now(timezone.utc)
    return [
        Tick(
            id=f"tick_{i}",
            author=f"user{i}",
            text=f"Test tweet about $TSLA #{i}",
            timestamp=now - timedelta(minutes=i),
            metrics={
                "like_count": 10 * (i + 1),
                "retweet_count": 5 * (i + 1),
                "reply_count": 2,
                "quote_count": 1
            },
            topic="$TSLA"
        )
        for i in range(10)
    ]


@pytest.fixture
def topic_manager(mock_x_adapter, mock_grok_adapter):
    """Create a TopicManager with mocked adapters."""
    manager = TopicManager(
        x_adapter=mock_x_adapter,
        grok_adapter=mock_grok_adapter,
        default_resolution="5m"
    )
    return manager


@pytest.fixture
def topic_manager_with_data(topic_manager, sample_ticks, mock_x_adapter):
    """TopicManager with a topic and some bars."""
    # Add a topic
    topic_manager.add_topic(
        topic_id="tsla",
        label="$TSLA",
        query="$TSLA OR Tesla",
        resolution="5m"
    )
    
    # Mock X adapter to return sample ticks
    mock_x_adapter.search_for_bar.return_value = sample_ticks[:5]
    
    # Create some bars manually
    aggregator = topic_manager._aggregators["tsla"]
    now = datetime.now(timezone.utc)
    
    for i in range(3):
        start = now - timedelta(minutes=(i + 1) * 5)
        end = start + timedelta(minutes=5)
        ticks = sample_ticks[i*2:(i+1)*2] if i < len(sample_ticks) // 2 else []
        
        aggregator.create_bar(
            topic="$TSLA",
            ticks=ticks,
            start=start,
            end=end,
            resolution="5m",
            generate_summary=False  # Skip Grok call in fixture
        )
    
    return topic_manager


# ============================================================================
# TopicManager Unit Tests
# ============================================================================

class TestTopicManager:
    """Test TopicManager functionality."""

    def test_add_topic(self, topic_manager):
        """Test adding a new topic."""
        topic = topic_manager.add_topic(
            topic_id="tsla",
            label="$TSLA",
            query="$TSLA OR Tesla",
            resolution="5m"
        )
        
        assert topic.id == "tsla"
        assert topic.label == "$TSLA"
        assert topic.query == "$TSLA OR Tesla"
        assert topic.status == TopicStatus.ACTIVE

    def test_add_duplicate_topic_fails(self, topic_manager):
        """Test that adding duplicate topic raises error."""
        topic_manager.add_topic("tsla", "$TSLA", "$TSLA")
        
        with pytest.raises(ValueError):
            topic_manager.add_topic("tsla", "$TSLA", "$TSLA")

    def test_add_invalid_resolution_fails(self, topic_manager):
        """Test that invalid resolution raises error."""
        with pytest.raises(ValueError):
            topic_manager.add_topic("tsla", "$TSLA", "$TSLA", resolution="invalid")

    def test_remove_topic(self, topic_manager):
        """Test removing a topic."""
        topic_manager.add_topic("tsla", "$TSLA", "$TSLA")
        
        assert topic_manager.remove_topic("tsla") is True
        assert topic_manager.get_topic("tsla") is None

    def test_remove_nonexistent_topic(self, topic_manager):
        """Test removing non-existent topic returns False."""
        assert topic_manager.remove_topic("nonexistent") is False

    def test_list_topics(self, topic_manager):
        """Test listing all topics."""
        topic_manager.add_topic("tsla", "$TSLA", "$TSLA")
        topic_manager.add_topic("aapl", "$AAPL", "$AAPL")
        
        topics = topic_manager.list_topics()
        
        assert len(topics) == 2
        assert {t.id for t in topics} == {"tsla", "aapl"}

    def test_pause_resume_topic(self, topic_manager):
        """Test pausing and resuming a topic."""
        topic_manager.add_topic("tsla", "$TSLA", "$TSLA")
        
        topic_manager.pause_topic("tsla")
        topic = topic_manager.get_topic("tsla")
        assert topic.status == TopicStatus.PAUSED
        
        topic_manager.resume_topic("tsla")
        topic = topic_manager.get_topic("tsla")
        assert topic.status == TopicStatus.ACTIVE

    def test_get_bars(self, topic_manager_with_data):
        """Test getting bars for a topic."""
        bars = topic_manager_with_data.get_bars("tsla", limit=10)
        
        assert len(bars) == 3
        # Should be sorted by time descending
        assert bars[0].start >= bars[1].start >= bars[2].start

    def test_get_latest_bar(self, topic_manager_with_data):
        """Test getting the latest bar."""
        latest = topic_manager_with_data.get_latest_bar("tsla")
        
        assert latest is not None
        bars = topic_manager_with_data.get_bars("tsla")
        assert latest.start == bars[0].start


class TestTopicManagerPolling:
    """Test TopicManager polling functionality."""

    @pytest.mark.asyncio
    async def test_poll_topic_success(self, topic_manager, sample_ticks, mock_x_adapter):
        """Test successful polling creates a bar."""
        topic_manager.add_topic("tsla", "$TSLA", "$TSLA")
        mock_x_adapter.search_for_bar.return_value = sample_ticks[:5]
        
        bar = await topic_manager.poll_topic("tsla", generate_summary=False)
        
        assert bar is not None
        assert bar.post_count == 5
        mock_x_adapter.search_for_bar.assert_called_once()

    @pytest.mark.asyncio
    async def test_poll_topic_empty_results(self, topic_manager, mock_x_adapter):
        """Test polling with no results creates empty bar."""
        topic_manager.add_topic("tsla", "$TSLA", "$TSLA")
        mock_x_adapter.search_for_bar.return_value = []
        
        bar = await topic_manager.poll_topic("tsla")
        
        assert bar is not None
        assert bar.post_count == 0

    @pytest.mark.asyncio
    async def test_poll_nonexistent_topic(self, topic_manager):
        """Test polling non-existent topic returns None."""
        bar = await topic_manager.poll_topic("nonexistent")
        assert bar is None

    @pytest.mark.asyncio
    async def test_poll_paused_topic_skipped(self, topic_manager, mock_x_adapter):
        """Test polling paused topic is skipped."""
        topic_manager.add_topic("tsla", "$TSLA", "$TSLA")
        topic_manager.pause_topic("tsla")
        
        bar = await topic_manager.poll_topic("tsla")
        
        assert bar is None
        mock_x_adapter.search_for_bar.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_topic_with_summary(self, topic_manager, sample_ticks, mock_x_adapter, mock_grok_adapter):
        """Test polling with Grok summary generation."""
        topic_manager.add_topic("tsla", "$TSLA", "$TSLA")
        mock_x_adapter.search_for_bar.return_value = sample_ticks[:5]
        
        bar = await topic_manager.poll_topic("tsla", generate_summary=True)
        
        assert bar is not None
        assert bar.summary is not None
        assert bar.summary.summary == "Test summary for the bar"
        mock_grok_adapter.summarize_bar.assert_called_once()

    @pytest.mark.asyncio
    async def test_poll_topic_x_error_sets_error_status(self, topic_manager, mock_x_adapter):
        """Test X API error sets topic to error status."""
        from adapter.x import XAPIError
        
        topic_manager.add_topic("tsla", "$TSLA", "$TSLA")
        mock_x_adapter.search_for_bar.side_effect = XAPIError("API Error")
        
        bar = await topic_manager.poll_topic("tsla")
        
        assert bar is None
        topic = topic_manager.get_topic("tsla")
        assert topic.status == TopicStatus.ERROR
        assert topic.last_error is not None


# ============================================================================
# TickPoller Tests
# ============================================================================

class TestTickPoller:
    """Test TickPoller background service."""

    @pytest.mark.asyncio
    async def test_poll_now_single_topic(self, topic_manager, sample_ticks, mock_x_adapter):
        """Test manual poll for single topic."""
        topic_manager.add_topic("tsla", "$TSLA", "$TSLA")
        mock_x_adapter.search_for_bar.return_value = sample_ticks[:3]
        
        poller = TickPoller(topic_manager, poll_interval=60, generate_summaries=False)
        await poller.poll_now("tsla")
        
        bars = topic_manager.get_bars("tsla")
        assert len(bars) == 1

    @pytest.mark.asyncio
    async def test_poll_now_all_topics(self, topic_manager, sample_ticks, mock_x_adapter):
        """Test manual poll for all topics."""
        topic_manager.add_topic("tsla", "$TSLA", "$TSLA")
        topic_manager.add_topic("aapl", "$AAPL", "$AAPL")
        mock_x_adapter.search_for_bar.return_value = sample_ticks[:2]
        
        poller = TickPoller(topic_manager, poll_interval=60, generate_summaries=False)
        await poller.poll_now()
        
        assert len(topic_manager.get_bars("tsla")) == 1
        assert len(topic_manager.get_bars("aapl")) == 1


# ============================================================================
# API Integration Tests
# ============================================================================

class TestAPIEndpoints:
    """Integration tests for API endpoints."""

    @pytest.fixture
    def client(self, topic_manager_with_data, mock_grok_adapter):
        """Create test client with mocked services."""
        from api import set_dependencies
        from aggregator import DigestService, BarAggregator
        
        # Create digest service with mock
        aggregator = BarAggregator(grok_adapter=mock_grok_adapter)
        digest_service = DigestService(
            grok_adapter=mock_grok_adapter,
            bar_aggregator=topic_manager_with_data._aggregators.get("tsla", aggregator)
        )
        
        poller = TickPoller(topic_manager_with_data, poll_interval=300)
        
        set_dependencies(topic_manager_with_data, poller, digest_service)
        
        return TestClient(app)

    def test_health_endpoint(self, client):
        """Test health check endpoint."""
        response = client.get("/api/v1/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "topics_count" in data

    def test_list_topics(self, client):
        """Test listing topics."""
        response = client.get("/api/v1/topics")
        
        assert response.status_code == 200
        topics = response.json()
        assert len(topics) >= 1
        assert any(t["id"] == "tsla" for t in topics)

    def test_get_topic(self, client):
        """Test getting a specific topic."""
        response = client.get("/api/v1/topics/tsla")
        
        assert response.status_code == 200
        topic = response.json()
        assert topic["id"] == "tsla"
        assert topic["label"] == "$TSLA"

    def test_get_nonexistent_topic(self, client):
        """Test getting non-existent topic returns 404."""
        response = client.get("/api/v1/topics/nonexistent")
        
        assert response.status_code == 404

    def test_create_topic(self, client):
        """Test creating a new topic."""
        response = client.post("/api/v1/topics", json={
            "label": "$AAPL",
            "query": "$AAPL OR Apple stock",
            "resolution": "5m"
        })
        
        assert response.status_code == 201
        topic = response.json()
        assert topic["label"] == "$AAPL"

    def test_delete_topic(self, client):
        """Test deleting a topic."""
        # First create a topic to delete
        client.post("/api/v1/topics", json={
            "label": "$TEST",
            "query": "test query"
        })
        
        response = client.delete("/api/v1/topics/test")
        assert response.status_code == 204

    def test_get_bars(self, client):
        """Test getting bars for a topic."""
        response = client.get("/api/v1/topics/tsla/bars?limit=10")
        
        assert response.status_code == 200
        bars = response.json()
        assert len(bars) >= 1
        
        bar = bars[0]
        assert "topic" in bar
        assert "post_count" in bar
        assert "start" in bar
        assert "end" in bar

    def test_get_bars_with_limit(self, client):
        """Test limiting bars returned."""
        response = client.get("/api/v1/topics/tsla/bars?limit=2")
        
        assert response.status_code == 200
        bars = response.json()
        assert len(bars) <= 2

    def test_get_latest_bar(self, client):
        """Test getting latest bar."""
        response = client.get("/api/v1/topics/tsla/bars/latest")
        
        assert response.status_code == 200
        # Could be null if no bars

    def test_pause_topic(self, client):
        """Test pausing a topic."""
        response = client.post("/api/v1/topics/tsla/pause")
        
        assert response.status_code == 200
        topic = response.json()
        assert topic["status"] == "paused"

    def test_resume_topic(self, client):
        """Test resuming a topic."""
        # First pause it
        client.post("/api/v1/topics/tsla/pause")
        
        response = client.post("/api/v1/topics/tsla/resume")
        
        assert response.status_code == 200
        topic = response.json()
        assert topic["status"] == "active"


class TestAPIDigest:
    """Test digest endpoint with mocks."""

    @pytest.fixture
    def client_with_digest(self, topic_manager_with_data, mock_grok_adapter):
        """Create test client configured for digest tests."""
        from api import set_dependencies
        from aggregator import DigestService
        
        # Use the topic manager's aggregator for the digest service
        digest_service = DigestService(
            grok_adapter=mock_grok_adapter,
            bar_aggregator=topic_manager_with_data._aggregators["tsla"]
        )
        
        poller = TickPoller(topic_manager_with_data, poll_interval=300)
        set_dependencies(topic_manager_with_data, poller, digest_service)
        
        return TestClient(app)

    def test_create_digest(self, client_with_digest, mock_grok_adapter):
        """Test creating a digest."""
        response = client_with_digest.post(
            "/api/v1/topics/tsla/digest?lookback_bars=12"
        )
        
        assert response.status_code == 200
        digest = response.json()
        assert digest["topic"] == "$TSLA"
        assert "overall_summary" in digest
        assert "key_developments" in digest


# ============================================================================
# Full Flow Integration Tests
# ============================================================================

class TestFullFlow:
    """Test complete user flows end-to-end."""

    @pytest.fixture
    def fresh_client(self, mock_x_adapter, mock_grok_adapter, sample_ticks):
        """Create a fresh test client with mocked adapters."""
        from api import set_dependencies
        from aggregator import DigestService, BarAggregator
        
        # Create fresh manager
        manager = TopicManager(
            x_adapter=mock_x_adapter,
            grok_adapter=mock_grok_adapter
        )
        
        aggregator = BarAggregator(grok_adapter=mock_grok_adapter)
        digest_service = DigestService(
            grok_adapter=mock_grok_adapter,
            bar_aggregator=aggregator
        )
        
        poller = TickPoller(manager, poll_interval=300, generate_summaries=True)
        set_dependencies(manager, poller, digest_service)
        
        # Setup mock to return sample ticks
        mock_x_adapter.search_for_bar.return_value = sample_ticks[:5]
        
        return TestClient(app)

    def test_complete_topic_lifecycle(self, fresh_client):
        """Test complete topic lifecycle: create → poll → get bars → delete."""
        # 1. Create topic
        response = fresh_client.post("/api/v1/topics", json={
            "label": "$NVDA",
            "query": "$NVDA OR Nvidia",
            "resolution": "5m"
        })
        assert response.status_code == 201
        topic_id = response.json()["id"]
        
        # 2. Poll for data
        response = fresh_client.post(f"/api/v1/topics/{topic_id}/poll")
        assert response.status_code == 200
        poll_result = response.json()
        assert poll_result["success"] is True
        
        # 3. Get bars
        response = fresh_client.get(f"/api/v1/topics/{topic_id}/bars")
        assert response.status_code == 200
        bars = response.json()
        assert len(bars) >= 1
        
        # 4. Verify bar has expected structure
        bar = bars[0]
        assert bar["topic"] == "$NVDA"
        assert bar["post_count"] == 5
        
        # 5. Delete topic
        response = fresh_client.delete(f"/api/v1/topics/{topic_id}")
        assert response.status_code == 204

    def test_multiple_topics_workflow(self, fresh_client, sample_ticks, mock_x_adapter):
        """Test managing multiple topics simultaneously."""
        # Create multiple topics
        topics = [
            {"label": "$TSLA", "query": "$TSLA"},
            {"label": "$AAPL", "query": "$AAPL"},
            {"label": "$MSFT", "query": "$MSFT"}
        ]
        
        created_ids = []
        for topic_data in topics:
            response = fresh_client.post("/api/v1/topics", json=topic_data)
            assert response.status_code == 201
            created_ids.append(response.json()["id"])
        
        # List topics
        response = fresh_client.get("/api/v1/topics")
        assert response.status_code == 200
        assert len(response.json()) >= 3
        
        # Poll each topic
        for topic_id in created_ids:
            response = fresh_client.post(f"/api/v1/topics/{topic_id}/poll")
            assert response.status_code == 200
        
        # Verify all have bars
        for topic_id in created_ids:
            response = fresh_client.get(f"/api/v1/topics/{topic_id}/bars")
            assert response.status_code == 200

    def test_bar_accumulation(self, fresh_client, sample_ticks, mock_x_adapter):
        """Test that multiple polls accumulate bars."""
        # Create topic
        response = fresh_client.post("/api/v1/topics", json={
            "label": "$TEST",
            "query": "test"
        })
        topic_id = response.json()["id"]
        
        # Poll multiple times (simulating different time windows)
        for i in range(3):
            # Change the ticks slightly each time
            mock_x_adapter.search_for_bar.return_value = sample_ticks[i:i+3]
            fresh_client.post(f"/api/v1/topics/{topic_id}/poll")
        
        # Should have accumulated 3 bars
        response = fresh_client.get(f"/api/v1/topics/{topic_id}/bars")
        bars = response.json()
        assert len(bars) == 3

