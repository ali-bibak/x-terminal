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
    TickStore, BarStore, BarGenerator, Bar, 
    RESOLUTION_MAP, DEFAULT_RESOLUTION, MIN_RESOLUTION_SECONDS,
    get_polling_window, get_bar_boundaries
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
        bar_store: Optional[BarStore] = None,
        default_resolution: str = DEFAULT_RESOLUTION
    ):
        self.x_adapter = x_adapter
        self.grok_adapter = grok_adapter
        self.default_resolution = default_resolution
        
        # Shared tick store for all topics
        self.tick_store = TickStore()
        
        # Bar store for pre-computed bars (instant GET access)
        self.bar_store = bar_store or BarStore()
        
        # Bar generator (uses tick store) - for on-demand fallback
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
        
        # Clear ticks and bars for this topic
        self.tick_store.clear_topic(label)
        self.bar_store.clear_topic(label)
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
        
        Reads from BarStore (pre-computed bars) for instant response.
        Falls back to on-demand generation if BarStore is empty.
        
        Args:
            topic_id: Topic ID
            resolution: Display resolution (default: topic's default)
            limit: Maximum bars to return
            generate_summaries: Whether to generate Grok summaries (only for fallback)
        
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
        
        # Try to get from BarStore first (instant access)
        bars = self.bar_store.get_bars(topic.label, resolution, limit)
        
        if bars:
            # Check if we have meaningful cached data WITH summaries
            bars_with_data = [b for b in bars if b.post_count > 0]
            bars_with_summaries = [b for b in bars_with_data if b.summary is not None]
            
            if bars_with_summaries:
                # Cache has bars with summaries - return immediately (FAST)
                # Note: some recent bars may not have summaries yet (BarScheduler is async)
                return bars
            
            # No summaries yet - check if ticks exist
            tick_count = self.tick_store.get_tick_count(topic.label)
            if tick_count == 0:
                # No ticks yet - return cached empty bars (FAST)
                return bars
            
            # Ticks exist but no summaries yet - return bars with post counts only (FAST)
            # Summaries will be populated by BarScheduler on next run
            logger.debug(f"BarStore has bars without summaries for {topic.label}/{resolution}, returning data-only bars")
            return bars
        
        # No cached bars - generate metrics only (no Grok calls for speed)
        logger.debug(f"BarStore empty for {topic.label}/{resolution}, generating metrics-only bars")
        return self.bar_generator.generate_bars(
            topic=topic.label,
            resolution=resolution,
            limit=limit,
            generate_summaries=False  # Summaries come from BarScheduler
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
        Reads from BarStore for instant access, falls back to async generation.
        """
        topic = self._topics.get(topic_id)
        if not topic:
            return []
        
        # Use topic's default resolution if not specified
        resolution = resolution or topic.resolution
        
        if resolution not in RESOLUTION_MAP:
            raise ValueError(f"Invalid resolution: {resolution}")
        
        # Try to get from BarStore first (instant access)
        bars = self.bar_store.get_bars(topic.label, resolution, limit)
        
        if bars:
            # Check if we have meaningful cached data WITH summaries
            bars_with_data = [b for b in bars if b.post_count > 0]
            bars_with_summaries = [b for b in bars_with_data if b.summary is not None]
            
            if bars_with_summaries:
                # Cache has bars with summaries - return immediately (FAST)
                # Note: some recent bars may not have summaries yet (BarScheduler is async)
                return bars
            
            # No summaries yet - check if ticks exist
            tick_count = self.tick_store.get_tick_count(topic.label)
            if tick_count == 0:
                # No ticks yet - return cached empty bars (FAST)
                return bars
            
            # Ticks exist but no summaries yet - return bars with post counts only (FAST)
            # Summaries will be populated by BarScheduler on next run
            logger.debug(f"BarStore has bars without summaries for {topic.label}/{resolution}, returning data-only bars")
            return bars
        
        # No cached bars - generate metrics only (no Grok calls for speed)
        logger.debug(f"BarStore empty for {topic.label}/{resolution}, generating metrics-only bars (async)")
        return await self.bar_generator.generate_bars_async(
            topic=topic.label,
            resolution=resolution,
            limit=limit,
            generate_summaries=False  # Summaries come from BarScheduler
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


class BarScheduler:
    """
    Background service that generates bars periodically for all resolutions.
    
    Each resolution runs on its own schedule:
    - 15s bars generated every 15 seconds
    - 1m bars generated every minute
    - 5m bars generated every 5 minutes
    - etc.
    
    Bars are stored in BarStore for instant GET access.
    """
    
    def __init__(
        self,
        topic_manager: TopicManager,
        bar_store: BarStore,
        bar_generator: BarGenerator,
        resolutions: Optional[List[str]] = None
    ):
        """
        Initialize BarScheduler.
        
        Args:
            topic_manager: TopicManager to get topic list
            bar_store: BarStore to save generated bars
            bar_generator: BarGenerator to create bars from ticks
            resolutions: List of resolutions to generate (default: all)
        """
        self.topic_manager = topic_manager
        self.bar_store = bar_store
        self.bar_generator = bar_generator
        self.resolutions = resolutions or list(RESOLUTION_MAP.keys())
        
        self._running = False
        self._tasks: Dict[str, asyncio.Task] = {}
        self._last_generated: Dict[str, Dict[str, datetime]] = {}  # {topic: {resolution: last_time}}
    
    async def start(self):
        """Start bar generation tasks for all resolutions."""
        if self._running:
            logger.warning("BarScheduler already running")
            return
        
        self._running = True
        
        # Create a task for each resolution
        for resolution in self.resolutions:
            interval = RESOLUTION_MAP[resolution]
            task = asyncio.create_task(self._generation_loop(resolution, interval))
            self._tasks[resolution] = task
            logger.info(f"BarScheduler started for {resolution} (every {interval}s)")
        
        # Generate initial bars for all topics immediately
        await self._generate_initial_bars()
    
    async def stop(self):
        """Stop all bar generation tasks."""
        self._running = False
        
        for resolution, task in self._tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self._tasks.clear()
        logger.info("BarScheduler stopped")
    
    async def _generate_initial_bars(self):
        """Generate initial set of bars for all topics (backfill)."""
        topics = self.topic_manager.list_topics()
        
        for topic in topics:
            if topic.status != TopicStatus.ACTIVE:
                continue
            
            for resolution in self.resolutions:
                try:
                    # Generate last N bars for this resolution
                    await self._generate_bars_for_topic(
                        topic.label, 
                        resolution, 
                        limit=50,  # Initial backfill
                        generate_summaries=False  # Skip Grok for backfill (fast)
                    )
                    logger.debug(f"Initial bars generated for {topic.label} at {resolution}")
                except Exception as e:
                    logger.error(f"Error generating initial bars for {topic.label}/{resolution}: {e}")
    
    async def _generation_loop(self, resolution: str, interval_seconds: int):
        """
        Generation loop for a specific resolution.
        Runs every interval_seconds to generate the latest bar.
        """
        while self._running:
            try:
                # Wait until the next bar boundary
                now = datetime.now(timezone.utc)
                next_boundary = self._get_next_boundary(resolution, now)
                wait_seconds = (next_boundary - now).total_seconds()
                
                if wait_seconds > 0:
                    # Add small buffer (2s) to ensure bar window is complete
                    await asyncio.sleep(wait_seconds + 2)
                
                # Generate bar for all active topics at this resolution
                await self._generate_current_bar(resolution)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in bar generation loop for {resolution}: {e}")
                await asyncio.sleep(5)  # Backoff on error
    
    def _get_next_boundary(self, resolution: str, now: datetime) -> datetime:
        """Get the next bar boundary time for a resolution."""
        interval = RESOLUTION_MAP[resolution]
        ts = now.timestamp()
        next_ts = (int(ts // interval) + 1) * interval
        return datetime.fromtimestamp(next_ts, tz=timezone.utc)
    
    async def _generate_current_bar(self, resolution: str):
        """Generate bars for all topics based on tick data."""
        topics = self.topic_manager.list_topics()
        active_topics = [t for t in topics if t.status == TopicStatus.ACTIVE]
        
        if not active_topics:
            return
        
        resolution_seconds = RESOLUTION_MAP[resolution]
        
        for topic in active_topics:
            try:
                # Get tick time range for this topic
                tick_range = self.topic_manager.tick_store.get_time_range(topic.label)
                if not tick_range:
                    continue
                
                oldest_tick, newest_tick = tick_range
                
                # Generate bars for time windows that have tick data
                # Start from the newest complete bar window
                bar_end_ts = int(newest_tick.timestamp() // resolution_seconds) * resolution_seconds
                bar_end = datetime.fromtimestamp(bar_end_ts, tz=timezone.utc)
                bar_start = bar_end - timedelta(seconds=resolution_seconds)
                
                # Check if this bar already exists in store
                existing = self.bar_store.get_latest_bar(topic.label, resolution)
                if existing and existing.start >= bar_start:
                    # Already have this bar or newer
                    continue
                
                # Generate the bar
                bar = await self.bar_generator.generate_bar_async(
                    topic=topic.label,
                    start=bar_start,
                    end=bar_end,
                    resolution=resolution,
                    generate_summary=True  # Generate fresh Grok summary
                )
                await self.bar_store.add_bar(bar)
                
                logger.info(
                    f"BarScheduler generated {resolution} bar for {topic.label}: "
                    f"{bar_start.strftime('%H:%M:%S')}-{bar_end.strftime('%H:%M:%S')} "
                    f"({bar.post_count} posts, summary={'yes' if bar.summary else 'no'})"
                )
                
            except Exception as e:
                logger.error(f"Error generating {resolution} bar for {topic.label}: {e}")
    
    async def _generate_bars_for_topic(
        self, 
        topic: str, 
        resolution: str, 
        limit: int = 50,
        generate_summaries: bool = True
    ):
        """Generate multiple bars for a topic at a resolution."""
        bars = await self.bar_generator.generate_bars_async(
            topic=topic,
            resolution=resolution,
            limit=limit,
            generate_summaries=generate_summaries
        )
        
        for bar in bars:
            await self.bar_store.add_bar(bar)
    
    async def regenerate_topic(self, topic_id: str, limit: int = 50, generate_summaries: bool = True):
        """
        Regenerate all bars for a topic (useful after adding new topic).
        
        Args:
            topic_id: Topic ID to regenerate
            limit: Number of historical bars to generate per resolution
            generate_summaries: Whether to generate Grok summaries
        """
        topic = self.topic_manager.get_topic(topic_id)
        if not topic:
            logger.warning(f"Topic {topic_id} not found")
            return
        
        for resolution in self.resolutions:
            try:
                await self._generate_bars_for_topic(
                    topic.label,
                    resolution,
                    limit=limit,
                    generate_summaries=generate_summaries
                )
                logger.info(f"Regenerated {resolution} bars for {topic.label}")
            except Exception as e:
                logger.error(f"Error regenerating {resolution} bars for {topic.label}: {e}")


__all__ = [
    "Topic",
    "TopicStatus",
    "TopicManager",
    "TickPoller",
    "BarScheduler",
    "RESOLUTION_MAP",
    "DEFAULT_RESOLUTION",
    "MIN_RESOLUTION_SECONDS",
]
