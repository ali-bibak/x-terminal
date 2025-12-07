"""
Unit tests for the core module (TopicManager, TickPoller).
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, AsyncMock, patch

from core import (
    Topic,
    TopicStatus,
    TopicManager,
    TickPoller
)
from adapter.models import Tick
from adapter.grok import BarSummary


# ============================================================================
# Topic Model Tests
# ============================================================================

class TestTopicModel:
    """Test the Topic Pydantic model."""

    def test_topic_creation(self):
        """Test creating a topic."""
        topic = Topic(
            id="tsla",
            label="$TSLA",
            query="$TSLA OR Tesla"
        )
        
        assert topic.id == "tsla"
        assert topic.label == "$TSLA"
        assert topic.status == TopicStatus.ACTIVE
        assert topic.resolution == "5m"
        assert topic.poll_count == 0

    def test_topic_with_custom_resolution(self):
        """Test topic with custom resolution."""
        topic = Topic(
            id="tsla",
            label="$TSLA",
            query="$TSLA",
            resolution="1h"
        )
        
        assert topic.resolution == "1h"

    def test_topic_status_enum(self):
        """Test topic status values."""
        assert TopicStatus.ACTIVE.value == "active"
        assert TopicStatus.PAUSED.value == "paused"
        assert TopicStatus.ERROR.value == "error"


# ============================================================================
# TopicManager Edge Cases
# ============================================================================

class TestTopicManagerEdgeCases:
    """Test edge cases for TopicManager."""

    @pytest.fixture
    def manager(self):
        """Create TopicManager with mocks."""
        x_adapter = Mock()
        x_adapter.is_configured = True
        x_adapter.search_for_bar = Mock(return_value=[])
        
        grok_adapter = Mock()
        grok_adapter.is_live = True
        grok_adapter.summarize_bar = Mock(return_value=BarSummary(
            summary="Test",
            key_themes=[],
            sentiment="neutral",
            post_count=0,
            engagement_level="low"
        ))
        
        return TopicManager(x_adapter, grok_adapter)

    def test_get_bars_empty_topic(self, manager):
        """Test getting bars for topic with no bars."""
        manager.add_topic("empty", "Empty", "empty")
        bars = manager.get_bars("empty")
        assert bars == []

    def test_get_bars_nonexistent_topic(self, manager):
        """Test getting bars for non-existent topic."""
        bars = manager.get_bars("nonexistent")
        assert bars == []

    def test_get_latest_bar_no_bars(self, manager):
        """Test getting latest bar when none exist."""
        manager.add_topic("empty", "Empty", "empty")
        bar = manager.get_latest_bar("empty")
        assert bar is None

    def test_pause_nonexistent_topic(self, manager):
        """Test pausing non-existent topic."""
        result = manager.pause_topic("nonexistent")
        assert result is False

    def test_resume_nonexistent_topic(self, manager):
        """Test resuming non-existent topic."""
        result = manager.resume_topic("nonexistent")
        assert result is False

    def test_multiple_topics_isolation(self, manager):
        """Test that topics are properly isolated."""
        # Add two topics
        manager.add_topic("topic1", "Topic 1", "query1")
        manager.add_topic("topic2", "Topic 2", "query2")
        
        # Pause one
        manager.pause_topic("topic1")
        
        # Check isolation
        assert manager.get_topic("topic1").status == TopicStatus.PAUSED
        assert manager.get_topic("topic2").status == TopicStatus.ACTIVE

    def test_resolution_validation(self, manager):
        """Test that valid resolutions are accepted."""
        valid_resolutions = ["1m", "5m", "10m", "15m", "30m", "1h"]
        
        for i, res in enumerate(valid_resolutions):
            manager.add_topic(f"topic_{i}", f"Topic {i}", f"query{i}", resolution=res)
            topic = manager.get_topic(f"topic_{i}")
            assert topic.resolution == res


# ============================================================================
# TickPoller Tests
# ============================================================================

class TestTickPollerUnit:
    """Unit tests for TickPoller."""

    @pytest.fixture
    def mock_manager(self):
        """Create mock TopicManager."""
        manager = Mock(spec=TopicManager)
        manager.list_topics.return_value = [
            Topic(id="topic1", label="Topic 1", query="q1"),
            Topic(id="topic2", label="Topic 2", query="q2", status=TopicStatus.PAUSED)
        ]
        manager.poll_topic = AsyncMock(return_value=None)
        return manager

    @pytest.mark.asyncio
    async def test_poller_initialization(self, mock_manager):
        """Test poller initialization."""
        poller = TickPoller(mock_manager, poll_interval=60)
        
        assert poller.poll_interval == 60
        assert poller.generate_summaries is True
        assert poller._running is False

    @pytest.mark.asyncio
    async def test_poller_start_stop(self, mock_manager):
        """Test poller start and stop."""
        poller = TickPoller(mock_manager, poll_interval=1)
        
        await poller.start()
        assert poller._running is True
        assert poller._task is not None
        
        await poller.stop()
        assert poller._running is False

    @pytest.mark.asyncio
    async def test_poll_all_filters_inactive(self, mock_manager):
        """Test that poll_all only polls active topics."""
        poller = TickPoller(mock_manager, poll_interval=60)
        await poller._poll_all_topics()
        
        # Should only call poll_topic for active topics
        assert mock_manager.poll_topic.call_count == 1
        mock_manager.poll_topic.assert_called_with("topic1", generate_summary=True)

    @pytest.mark.asyncio
    async def test_poll_now_specific_topic(self, mock_manager):
        """Test poll_now with specific topic."""
        poller = TickPoller(mock_manager, poll_interval=60)
        await poller.poll_now("topic1")
        
        mock_manager.poll_topic.assert_called_once_with("topic1", generate_summary=True)

    @pytest.mark.asyncio
    async def test_poll_now_all_topics(self, mock_manager):
        """Test poll_now without topic polls all."""
        poller = TickPoller(mock_manager, poll_interval=60)
        await poller.poll_now()
        
        # Should poll active topics
        mock_manager.poll_topic.assert_called()


# ============================================================================
# Integration Tests
# ============================================================================

class TestCoreIntegration:
    """Integration tests for core module."""

    @pytest.fixture
    def full_setup(self):
        """Create full setup with mocked adapters."""
        x_adapter = Mock()
        x_adapter.is_configured = True
        
        grok_adapter = Mock()
        grok_adapter.is_live = True
        grok_adapter.summarize_bar = Mock(return_value=BarSummary(
            summary="Integration test summary",
            key_themes=["test"],
            sentiment="positive",
            post_count=3,
            engagement_level="medium"
        ))
        
        manager = TopicManager(x_adapter, grok_adapter)
        poller = TickPoller(manager, poll_interval=60, generate_summaries=True)
        
        return manager, poller, x_adapter, grok_adapter

    def test_full_topic_workflow(self, full_setup):
        """Test complete topic workflow."""
        manager, poller, x_adapter, grok_adapter = full_setup
        
        # Add topic
        topic = manager.add_topic("test", "Test Topic", "test query")
        assert topic.status == TopicStatus.ACTIVE
        
        # Pause
        manager.pause_topic("test")
        assert manager.get_topic("test").status == TopicStatus.PAUSED
        
        # Resume
        manager.resume_topic("test")
        assert manager.get_topic("test").status == TopicStatus.ACTIVE
        
        # List
        topics = manager.list_topics()
        assert len(topics) == 1
        
        # Remove
        manager.remove_topic("test")
        assert manager.get_topic("test") is None

    @pytest.mark.asyncio
    async def test_poll_creates_bars(self, full_setup):
        """Test that polling creates bars."""
        manager, poller, x_adapter, grok_adapter = full_setup
        
        # Setup mock ticks
        now = datetime.now(timezone.utc)
        ticks = [
            Tick(
                id=f"t{i}",
                author=f"user{i}",
                text=f"Test {i}",
                timestamp=now - timedelta(minutes=i),
                metrics={"like_count": i * 10},
                topic="Test"
            )
            for i in range(5)
        ]
        x_adapter.search_for_bar = Mock(return_value=ticks)
        
        # Add topic and poll
        manager.add_topic("test", "Test", "test")
        await manager.poll_topic("test", generate_summary=True)
        
        # Verify bar was created
        bars = manager.get_bars("test")
        assert len(bars) == 1
        assert bars[0].post_count == 5
        
        # Verify Grok was called
        grok_adapter.summarize_bar.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_handling_in_poll(self, full_setup):
        """Test error handling during poll."""
        manager, poller, x_adapter, grok_adapter = full_setup
        
        from adapter.x import XRateLimitError
        x_adapter.search_for_bar = Mock(side_effect=XRateLimitError("Rate limited"))
        
        manager.add_topic("test", "Test", "test")
        bar = await manager.poll_topic("test")
        
        # Should return None and set error status
        assert bar is None
        topic = manager.get_topic("test")
        assert topic.status == TopicStatus.ERROR
        assert "Rate limited" in topic.last_error

