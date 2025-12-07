"""
Core services for X Terminal backend.
- TopicManager: Manages watched topics and their state
- TickPoller: Background service for polling X API

Architecture:
- Raw ticks are stored (not bars)
- Bars are generated on-demand at any resolution
- Resolution is a query parameter
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from enum import Enum

from pydantic import BaseModel, Field

from adapter.x import XAdapter, XAdapterError
from adapter.grok import GrokAdapter
from adapter.models import Tick
from aggregator import (
    TickStore, BarGenerator, Bar, 
    RESOLUTION_MAP, DEFAULT_RESOLUTION, MIN_RESOLUTION_SECONDS,
    get_polling_window
)

# Import monitoring (lazy to avoid circular imports)
_monitor = None

def _get_monitor():
    global _monitor
    if _monitor is None:
        try:
            from monitoring import monitor
            _monitor = monitor
        except ImportError:
            _monitor = None
    return _monitor

logger = logging.getLogger(__name__)


class TopicStatus(str, Enum):
    """Status of a watched topic."""
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"


class Topic(BaseModel):
    """
    A watched topic configuration.
    
    Note: resolution is the DEFAULT display resolution.
    Bars can be generated at any resolution via query parameter.
    """
    id: str = Field(description="Unique topic ID")
    label: str = Field(description="Display label (e.g., '$TSLA')")
    query: str = Field(description="X search query")
    resolution: str = Field(default=DEFAULT_RESOLUTION, description="Default display resolution")
    status: TopicStatus = Field(default=TopicStatus.ACTIVE)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_poll: Optional[datetime] = Field(default=None)
    last_error: Optional[str] = Field(default=None)
    poll_count: int = Field(default=0)
    tick_count: int = Field(default=0)


class TopicManager:
    """
    Manages watched topics and their tick data.
    
    Architecture:
    - Stores raw ticks (not pre-computed bars)
    - Generates bars on-demand at any resolution
    - Resolution is a query-time parameter
    
    Usage:
        manager = TopicManager(x_adapter, grok_adapter)
        
        # Add a topic
        topic = manager.add_topic("tsla", "$TSLA", "$TSLA OR Tesla")
        
        # Poll for new ticks (stores raw ticks)
        await manager.poll_topic("tsla")
        
        # Get bars at ANY resolution (generated on-demand)
        bars_15s = manager.get_bars("tsla", resolution="15s")
        bars_1m = manager.get_bars("tsla", resolution="1m")
        bars_5m = manager.get_bars("tsla", resolution="5m")
    """
    
    def __init__(
        self,
        x_adapter: XAdapter,
        grok_adapter: GrokAdapter,
        default_resolution: str = DEFAULT_RESOLUTION
    ):
        self.x_adapter = x_adapter
        self.grok_adapter = grok_adapter
        self.default_resolution = default_resolution
        
        # Shared tick store for all topics
        self.tick_store = TickStore()
        
        # Bar generator (uses tick store)
        self.bar_generator = BarGenerator(grok_adapter, self.tick_store)
        
        # Topic configurations
        self._topics: Dict[str, Topic] = {}
    
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
            resolution: Default display resolution (bars generated on-demand)
        
        Returns:
            The created Topic
        """
        if topic_id in self._topics:
            raise ValueError(f"Topic '{topic_id}' already exists")
        
        resolution = resolution or self.default_resolution
        if resolution not in RESOLUTION_MAP:
            raise ValueError(f"Invalid resolution: {resolution}. Valid: {list(RESOLUTION_MAP.keys())}")
        
        topic = Topic(
            id=topic_id,
            label=label,
            query=query,
            resolution=resolution
        )
        
        self._topics[topic_id] = topic
        logger.info(f"Added topic: {topic_id} ({label}) with query '{query}' (default resolution: {resolution})")
        
        # Record topic added event
        mon = _get_monitor()
        if mon:
            from monitoring import EventType
            mon.activity.add_event(
                EventType.TOPIC_ADDED,
                topic=label,
                topic_id=topic_id,
                query=query,
                resolution=resolution
            )
        
        return topic
    
    def remove_topic(self, topic_id: str) -> bool:
        """Remove a topic from watching."""
        topic = self._topics.get(topic_id)
        if not topic:
            return False
        
        label = topic.label
        
        # Clear ticks for this topic
        self.tick_store.clear_topic(label)
        del self._topics[topic_id]
        
        logger.info(f"Removed topic: {topic_id}")
        
        # Record topic removed event
        mon = _get_monitor()
        if mon:
            from monitoring import EventType
            mon.activity.add_event(EventType.TOPIC_REMOVED, topic=label, topic_id=topic_id)
        
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
    
    def set_topic_resolution(self, topic_id: str, resolution: str) -> bool:
        """
        Change the default display resolution for a topic.
        
        This doesn't affect stored data - just changes the default
        resolution used when querying bars.
        """
        if resolution not in RESOLUTION_MAP:
            raise ValueError(f"Invalid resolution: {resolution}")
        
        topic = self._topics.get(topic_id)
        if not topic:
            return False
        
        topic.resolution = resolution
        return True
    
    async def poll_topic(self, topic_id: str) -> int:
        """
        Poll X API for a topic and store raw ticks.
        
        Args:
            topic_id: Topic to poll
        
        Returns:
            Number of new ticks added
        """
        topic = self._topics.get(topic_id)
        if not topic:
            logger.warning(f"Topic not found: {topic_id}")
            return 0
        
        if topic.status != TopicStatus.ACTIVE:
            logger.debug(f"Topic {topic_id} is not active, skipping poll")
            return 0
        
        # Get a safe polling window (respects X API constraints)
        start_time, end_time = get_polling_window(min_age_seconds=15)
        
        try:
            # Fetch ticks from X API
            ticks = self.x_adapter.search_for_bar(
                query=topic.query,
                topic=topic.label,
                start_time=start_time,
                end_time=end_time,
                max_results=100
            )
            
            # Store raw ticks
            new_count = self.tick_store.add_ticks(topic.label, ticks)
            
            # Update topic stats
            topic.last_poll = datetime.now(timezone.utc)
            topic.poll_count += 1
            topic.tick_count = self.tick_store.get_tick_count(topic.label)
            topic.last_error = None
            
            if new_count > 0:
                logger.info(f"Poll {topic_id}: +{new_count} ticks ({start_time.strftime('%H:%M:%S')} - {end_time.strftime('%H:%M:%S')})")
            else:
                logger.debug(f"Poll {topic_id}: no new ticks")
            
            # Record poll and tick events
            mon = _get_monitor()
            if mon:
                from monitoring import EventType
                mon.activity.add_event(
                    EventType.POLL,
                    topic=topic.label,
                    new_ticks=new_count,
                    total_ticks=topic.tick_count
                )
                if new_count > 0:
                    mon.metrics.record_ticks(new_count)
                    mon.activity.add_event(
                        EventType.TICK_ADDED,
                        topic=topic.label,
                        count=new_count
                    )
            
            return new_count
            
        except XAdapterError as e:
            topic.status = TopicStatus.ERROR
            topic.last_error = str(e)
            logger.error(f"Error polling {topic_id}: {e}")
            
            # Record error event
            mon = _get_monitor()
            if mon:
                from monitoring import EventType
                mon.activity.add_event(EventType.ERROR, topic=topic.label, error=str(e)[:200])
            
            return 0
        except Exception as e:
            topic.status = TopicStatus.ERROR
            topic.last_error = str(e)
            logger.error(f"Unexpected error polling {topic_id}: {e}")
            
            # Record error event
            mon = _get_monitor()
            if mon:
                from monitoring import EventType
                mon.activity.add_event(EventType.ERROR, topic=topic.label, error=str(e)[:200])
            
            return 0
    
    def get_bars(
        self,
        topic_id: str,
        resolution: Optional[str] = None,
        limit: int = 50,
        generate_summaries: bool = True
    ) -> List[Bar]:
        """
        Get bars for a topic at the specified resolution.
        
        Bars are generated ON-DEMAND from raw ticks.
        Each bar gets its own fresh Grok summary.
        
        Args:
            topic_id: Topic ID
            resolution: Display resolution (default: topic's default)
            limit: Maximum bars to return
            generate_summaries: Whether to generate Grok summaries
        
        Returns:
            List of bars, most recent first
        """
        topic = self._topics.get(topic_id)
        if not topic:
            return []
        
        # Use topic's default resolution if not specified
        resolution = resolution or topic.resolution
        
        if resolution not in RESOLUTION_MAP:
            raise ValueError(f"Invalid resolution: {resolution}")
        
        # Generate bars on-demand from stored ticks
        return self.bar_generator.generate_bars(
            topic=topic.label,
            resolution=resolution,
            limit=limit,
            generate_summaries=generate_summaries
        )
    
    def get_latest_bar(
        self, 
        topic_id: str, 
        resolution: Optional[str] = None,
        generate_summary: bool = True
    ) -> Optional[Bar]:
        """Get the most recent bar for a topic."""
        bars = self.get_bars(topic_id, resolution=resolution, limit=1, generate_summaries=generate_summary)
        return bars[0] if bars else None

    # -------------------------------------------------------------------------
    # Async versions (non-blocking)
    # -------------------------------------------------------------------------

    async def get_bars_async(
        self,
        topic_id: str,
        resolution: Optional[str] = None,
        limit: int = 50,
        generate_summaries: bool = True
    ) -> List[Bar]:
        """
        Async version of get_bars.
        Generates bars without blocking the event loop.
        """
        topic = self._topics.get(topic_id)
        if not topic:
            return []
        
        # Use topic's default resolution if not specified
        resolution = resolution or topic.resolution
        
        if resolution not in RESOLUTION_MAP:
            raise ValueError(f"Invalid resolution: {resolution}")
        
        # Generate bars on-demand from stored ticks (async)
        return await self.bar_generator.generate_bars_async(
            topic=topic.label,
            resolution=resolution,
            limit=limit,
            generate_summaries=generate_summaries
        )

    async def get_latest_bar_async(
        self, 
        topic_id: str, 
        resolution: Optional[str] = None,
        generate_summary: bool = True
    ) -> Optional[Bar]:
        """Async version: Get the most recent bar for a topic."""
        bars = await self.get_bars_async(
            topic_id, 
            resolution=resolution, 
            limit=1, 
            generate_summaries=generate_summary
        )
        return bars[0] if bars else None
    
    def get_tick_count(self, topic_id: str) -> int:
        """Get raw tick count for a topic."""
        topic = self._topics.get(topic_id)
        if not topic:
            return 0
        return self.tick_store.get_tick_count(topic.label)


class TickPoller:
    """
    Background service that polls X API for all active topics.
    
    Polls at minimum resolution (15s) to collect granular tick data.
    Bars are generated on-demand at any resolution.
    
    Usage:
        poller = TickPoller(topic_manager)
        await poller.start()  # Polls every 15s by default
        await poller.stop()
    """
    
    def __init__(
        self,
        topic_manager: TopicManager,
        poll_interval: int = MIN_RESOLUTION_SECONDS,  # Default: 15s
    ):
        self.topic_manager = topic_manager
        self.poll_interval = poll_interval
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
        
        for topic in active_topics:
            try:
                await self.topic_manager.poll_topic(topic.id)
            except Exception as e:
                logger.error(f"Error polling topic {topic.id}: {e}")
            
            # Small delay between topics to avoid rate limits
            await asyncio.sleep(0.5)
    
    async def poll_now(self, topic_id: Optional[str] = None):
        """
        Manually trigger a poll.
        
        Args:
            topic_id: Specific topic to poll, or None to poll all
        """
        if topic_id:
            await self.topic_manager.poll_topic(topic_id)
        else:
            await self._poll_all_topics()


__all__ = [
    "Topic",
    "TopicStatus",
    "TopicManager",
    "TickPoller",
    "RESOLUTION_MAP",
    "DEFAULT_RESOLUTION",
    "MIN_RESOLUTION_SECONDS",
]
