"""
Core services for X Terminal backend.
- TopicManager: Manages watched topics and their state
- TickPoller: Background service for polling X API
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Callable
from enum import Enum

from pydantic import BaseModel, Field

from adapter.x import XAdapter, XAdapterError
from adapter.grok import GrokAdapter
from adapter.models import Tick
from aggregator import BarAggregator, Bar, get_previous_bar_window, RESOLUTION_MAP

logger = logging.getLogger(__name__)


class TopicStatus(str, Enum):
    """Status of a watched topic."""
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"


class Topic(BaseModel):
    """A watched topic configuration."""
    id: str = Field(description="Unique topic ID")
    label: str = Field(description="Display label (e.g., '$TSLA')")
    query: str = Field(description="X search query")
    resolution: str = Field(default="5m", description="Bar resolution")
    status: TopicStatus = Field(default=TopicStatus.ACTIVE)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_poll: Optional[datetime] = Field(default=None)
    last_error: Optional[str] = Field(default=None)
    poll_count: int = Field(default=0)
    tick_count: int = Field(default=0)


class TopicManager:
    """
    Manages watched topics and their associated bars.
    
    Usage:
        manager = TopicManager(x_adapter, grok_adapter)
        
        # Add a topic to watch
        topic = manager.add_topic("tsla", "$TSLA", "$TSLA OR Tesla")
        
        # Poll for new ticks and create bars
        await manager.poll_topic("tsla")
        
        # Get bars for a topic
        bars = manager.get_bars("tsla", limit=50)
    """
    
    def __init__(
        self,
        x_adapter: XAdapter,
        grok_adapter: GrokAdapter,
        default_resolution: str = "5m"
    ):
        self.x_adapter = x_adapter
        self.grok_adapter = grok_adapter
        self.default_resolution = default_resolution
        
        # In-memory stores
        self._topics: Dict[str, Topic] = {}
        self._aggregators: Dict[str, BarAggregator] = {}
    
    def add_topic(
        self,
        topic_id: str,
        label: str,
        query: str,
        resolution: Optional[str] = None
    ) -> Topic:
        """
        Add a new topic to watch.
        
        Args:
            topic_id: Unique identifier
            label: Display label
            query: X search query
            resolution: Bar resolution (default: 5m)
        
        Returns:
            The created Topic
        """
        if topic_id in self._topics:
            raise ValueError(f"Topic '{topic_id}' already exists")
        
        resolution = resolution or self.default_resolution
        if resolution not in RESOLUTION_MAP:
            raise ValueError(f"Invalid resolution: {resolution}")
        
        topic = Topic(
            id=topic_id,
            label=label,
            query=query,
            resolution=resolution
        )
        
        self._topics[topic_id] = topic
        self._aggregators[topic_id] = BarAggregator(
            grok_adapter=self.grok_adapter,
            default_resolution=resolution
        )
        
        logger.info(f"Added topic: {topic_id} ({label}) with query '{query}'")
        return topic
    
    def remove_topic(self, topic_id: str) -> bool:
        """Remove a topic from watching."""
        if topic_id not in self._topics:
            return False
        
        del self._topics[topic_id]
        if topic_id in self._aggregators:
            del self._aggregators[topic_id]
        
        logger.info(f"Removed topic: {topic_id}")
        return True
    
    def get_topic(self, topic_id: str) -> Optional[Topic]:
        """Get a topic by ID."""
        return self._topics.get(topic_id)
    
    def list_topics(self) -> List[Topic]:
        """List all topics."""
        return list(self._topics.values())
    
    def pause_topic(self, topic_id: str) -> bool:
        """Pause polling for a topic."""
        topic = self._topics.get(topic_id)
        if not topic:
            return False
        topic.status = TopicStatus.PAUSED
        return True
    
    def resume_topic(self, topic_id: str) -> bool:
        """Resume polling for a topic."""
        topic = self._topics.get(topic_id)
        if not topic:
            return False
        topic.status = TopicStatus.ACTIVE
        topic.last_error = None
        return True
    
    async def poll_topic(self, topic_id: str, generate_summary: bool = True) -> Optional[Bar]:
        """
        Poll X API for a topic and create a bar for the previous window.
        
        Args:
            topic_id: Topic to poll
            generate_summary: Whether to generate Grok summary
        
        Returns:
            The created Bar, or None if no ticks found
        """
        topic = self._topics.get(topic_id)
        if not topic:
            logger.warning(f"Topic not found: {topic_id}")
            return None
        
        if topic.status != TopicStatus.ACTIVE:
            logger.debug(f"Topic {topic_id} is not active, skipping poll")
            return None
        
        aggregator = self._aggregators.get(topic_id)
        if not aggregator:
            logger.error(f"No aggregator for topic: {topic_id}")
            return None
        
        # Get the previous bar window
        start_time, end_time = get_previous_bar_window(topic.resolution)
        
        try:
            # Fetch ticks from X API
            ticks = self.x_adapter.search_for_bar(
                query=topic.query,
                topic=topic.label,
                start_time=start_time,
                end_time=end_time,
                max_results=100
            )
            
            # Update topic stats
            topic.last_poll = datetime.now(timezone.utc)
            topic.poll_count += 1
            topic.tick_count += len(ticks)
            topic.last_error = None
            
            if not ticks:
                logger.info(f"No ticks for {topic_id} in window {start_time} - {end_time}")
                # Still create an empty bar to show there was no activity
                bar = aggregator.create_bar(
                    topic=topic.label,
                    ticks=[],
                    start=start_time,
                    end=end_time,
                    resolution=topic.resolution,
                    generate_summary=False
                )
                return bar
            
            # Create bar with ticks
            bar = aggregator.create_bar(
                topic=topic.label,
                ticks=ticks,
                start=start_time,
                end=end_time,
                resolution=topic.resolution,
                generate_summary=generate_summary
            )
            
            logger.info(f"Created bar for {topic_id}: {len(ticks)} ticks, {start_time} - {end_time}")
            return bar
            
        except XAdapterError as e:
            topic.status = TopicStatus.ERROR
            topic.last_error = str(e)
            logger.error(f"Error polling {topic_id}: {e}")
            return None
        except Exception as e:
            topic.status = TopicStatus.ERROR
            topic.last_error = str(e)
            logger.error(f"Unexpected error polling {topic_id}: {e}")
            return None
    
    def get_bars(
        self,
        topic_id: str,
        limit: int = 50,
        resolution: Optional[str] = None
    ) -> List[Bar]:
        """
        Get bars for a topic.
        
        Args:
            topic_id: Topic ID
            limit: Maximum bars to return
            resolution: Filter by resolution (optional)
        
        Returns:
            List of bars, most recent first
        """
        aggregator = self._aggregators.get(topic_id)
        if not aggregator:
            return []
        
        topic = self._topics.get(topic_id)
        if not topic:
            return []
        
        return aggregator.get_bars(topic.label, limit=limit)
    
    def get_latest_bar(self, topic_id: str) -> Optional[Bar]:
        """Get the most recent bar for a topic."""
        bars = self.get_bars(topic_id, limit=1)
        return bars[0] if bars else None


class TickPoller:
    """
    Background service that polls X API for all active topics.
    
    Usage:
        poller = TickPoller(topic_manager, poll_interval=300)
        
        # Start polling (runs in background)
        await poller.start()
        
        # Stop polling
        await poller.stop()
    """
    
    def __init__(
        self,
        topic_manager: TopicManager,
        poll_interval: int = 300,  # 5 minutes default
        generate_summaries: bool = True
    ):
        self.topic_manager = topic_manager
        self.poll_interval = poll_interval
        self.generate_summaries = generate_summaries
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start the background polling task."""
        if self._running:
            logger.warning("Poller already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(f"TickPoller started with {self.poll_interval}s interval")
    
    async def stop(self):
        """Stop the background polling task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("TickPoller stopped")
    
    async def _poll_loop(self):
        """Main polling loop."""
        while self._running:
            try:
                await self._poll_all_topics()
            except Exception as e:
                logger.error(f"Error in poll loop: {e}")
            
            # Wait for next poll interval
            await asyncio.sleep(self.poll_interval)
    
    async def _poll_all_topics(self):
        """Poll all active topics."""
        topics = self.topic_manager.list_topics()
        active_topics = [t for t in topics if t.status == TopicStatus.ACTIVE]
        
        if not active_topics:
            logger.debug("No active topics to poll")
            return
        
        logger.info(f"Polling {len(active_topics)} active topics")
        
        for topic in active_topics:
            try:
                await self.topic_manager.poll_topic(
                    topic.id,
                    generate_summary=self.generate_summaries
                )
            except Exception as e:
                logger.error(f"Error polling topic {topic.id}: {e}")
            
            # Small delay between topics to avoid rate limits
            await asyncio.sleep(1)
    
    async def poll_now(self, topic_id: Optional[str] = None):
        """
        Manually trigger a poll.
        
        Args:
            topic_id: Specific topic to poll, or None to poll all
        """
        if topic_id:
            await self.topic_manager.poll_topic(topic_id, generate_summary=self.generate_summaries)
        else:
            await self._poll_all_topics()


__all__ = [
    "Topic",
    "TopicStatus",
    "TopicManager",
    "TickPoller",
]

