"""
FastAPI routes for X Terminal backend.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field

from core import TopicManager, Topic, TopicStatus, TickPoller, RESOLUTION_MAP, DEFAULT_RESOLUTION
from aggregator import Bar, DigestService
from monitoring import monitor, get_rate_limit_status, EventType

logger = logging.getLogger(__name__)

# Router for API endpoints
router = APIRouter(prefix="/api/v1", tags=["X Terminal"])


# ============================================================================
# Request/Response Models
# ============================================================================

class CreateTopicRequest(BaseModel):
    """Request to create a new topic."""
    label: str = Field(description="Display label (e.g., '$TSLA')")
    query: str = Field(description="X search query")
    resolution: str = Field(default=DEFAULT_RESOLUTION, description="Default display resolution (bars generated on-demand)")


class TopicResponse(BaseModel):
    """Topic information response."""
    id: str
    label: str
    query: str
    resolution: str
    status: str
    created_at: datetime
    last_poll: Optional[datetime]
    last_error: Optional[str]
    poll_count: int
    tick_count: int

    @classmethod
    def from_topic(cls, topic: Topic) -> "TopicResponse":
        return cls(
            id=topic.id,
            label=topic.label,
            query=topic.query,
            resolution=topic.resolution,
            status=topic.status.value,
            created_at=topic.created_at,
            last_poll=topic.last_poll,
            last_error=topic.last_error,
            poll_count=topic.poll_count,
            tick_count=topic.tick_count
        )


class BarResponse(BaseModel):
    """Bar data response."""
    topic: str
    resolution: str
    start: datetime
    end: datetime
    post_count: int
    total_likes: int
    total_retweets: int
    total_replies: int
    total_quotes: int
    sample_post_ids: List[str]
    summary: Optional[str]
    sentiment: Optional[float] = Field(default=None, description="Sentiment score 0.0-1.0 (0.5=neutral)")
    key_themes: List[str]
    highlight_posts: List[str]

    @classmethod
    def from_bar(cls, bar: Bar) -> "BarResponse":
        return cls(
            topic=bar.topic,
            resolution=bar.resolution,
            start=bar.start,
            end=bar.end,
            post_count=bar.post_count,
            total_likes=bar.total_likes,
            total_retweets=bar.total_retweets,
            total_replies=bar.total_replies,
            total_quotes=bar.total_quotes,
            sample_post_ids=bar.sample_post_ids,
            summary=bar.summary.summary if bar.summary else None,
            sentiment=bar.summary.sentiment if bar.summary else None,
            key_themes=bar.summary.key_themes if bar.summary else [],
            highlight_posts=bar.summary.highlight_posts if bar.summary else []
        )


class DigestResponse(BaseModel):
    """Topic digest response."""
    topic: str
    generated_at: datetime
    time_range: str
    overall_summary: str
    key_developments: List[str]
    trending_elements: List[str]
    sentiment_trend: str
    recommendations: List[str]


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    timestamp: datetime
    topics_count: int
    active_topics: int


class PollResponse(BaseModel):
    """Response after triggering a poll."""
    success: bool
    message: str
    new_ticks: int = 0
    total_ticks: int = 0


class LocationRequest(BaseModel):
    """Request to resolve a location to WOEID."""
    latitude: Optional[float] = Field(default=None, description="Latitude (-90 to 90)")
    longitude: Optional[float] = Field(default=None, description="Longitude (-180 to 180)")
    ip_address: Optional[str] = Field(default=None, description="IP address to geolocate (use 'auto' to extract from request)")


class WOEIDResponse(BaseModel):
    """WOEID resolution response."""
    woeid: int
    location_name: str
    country: str
    source: str = Field(description="Source of location: 'coordinates', 'ip', or 'default'")
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class TrendingTopic(BaseModel):
    """A single trending topic."""
    name: str = Field(description="Topic name/hashtag")
    url: str = Field(description="X URL for the topic")
    query: str = Field(description="Search query string")
    tweet_volume: Optional[int] = Field(default=None, description="Number of tweets (may be None)")
    rank: int = Field(description="Ranking position (1-based)")


class TrendingTopicsResponse(BaseModel):
    """Trending topics response with cache metadata."""
    woeid: int
    location_name: str
    country: str
    trends: List[TrendingTopic]
    cached: bool = Field(description="Whether this response was served from cache")
    cached_at: Optional[datetime] = Field(default=None, description="When trends were cached")
    expires_at: Optional[datetime] = Field(default=None, description="When cache expires")


class LocationListResponse(BaseModel):
    """Response with list of available locations."""
    locations: List[dict]


# ============================================================================
# Dependency Injection - these get set by the main app
# ============================================================================

_topic_manager: Optional[TopicManager] = None
_tick_poller: Optional[TickPoller] = None
_digest_service: Optional[DigestService] = None

# Location and trends services
_location_service = None
_trends_cache = None
_x_adapter = None


def set_dependencies(
    topic_manager: TopicManager,
    tick_poller: TickPoller,
    digest_service: DigestService
):
    """Set the service dependencies (called from main app)."""
    global _topic_manager, _tick_poller, _digest_service
    _topic_manager = topic_manager
    _tick_poller = tick_poller
    _digest_service = digest_service


def set_location_dependencies(location_service, trends_cache, x_adapter):
    """Set the location and trends service dependencies (called from main app)."""
    global _location_service, _trends_cache, _x_adapter
    _location_service = location_service
    _trends_cache = trends_cache
    _x_adapter = x_adapter


def get_topic_manager() -> TopicManager:
    if _topic_manager is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return _topic_manager


def get_tick_poller() -> TickPoller:
    if _tick_poller is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return _tick_poller


def get_digest_service() -> DigestService:
    if _digest_service is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return _digest_service


def get_location_service():
    if _location_service is None:
        raise HTTPException(status_code=503, detail="Location service not initialized")
    return _location_service


def get_trends_cache():
    if _trends_cache is None:
        raise HTTPException(status_code=503, detail="Trends cache not initialized")
    return _trends_cache


def get_x_adapter():
    if _x_adapter is None:
        raise HTTPException(status_code=503, detail="X adapter not initialized")
    return _x_adapter


# ============================================================================
# Routes
# ============================================================================

@router.get("/health", response_model=HealthResponse)
async def health_check(manager: TopicManager = Depends(get_topic_manager)):
    """Health check endpoint."""
    topics = manager.list_topics()
    active = [t for t in topics if t.status == TopicStatus.ACTIVE]
    
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc),
        topics_count=len(topics),
        active_topics=len(active)
    )


# ----------------------------------------------------------------------------
# Topics
# ----------------------------------------------------------------------------

@router.get("/topics", response_model=List[TopicResponse])
async def list_topics(manager: TopicManager = Depends(get_topic_manager)):
    """List all watched topics."""
    topics = manager.list_topics()
    return [TopicResponse.from_topic(t) for t in topics]


@router.post("/topics", response_model=TopicResponse, status_code=201)
async def create_topic(
    request: CreateTopicRequest,
    manager: TopicManager = Depends(get_topic_manager)
):
    """Start watching a new topic."""
    # Generate ID from label (lowercase, remove special chars)
    topic_id = request.label.lower().replace("$", "").replace(" ", "_")
    
    try:
        topic = manager.add_topic(
            topic_id=topic_id,
            label=request.label,
            query=request.query,
            resolution=request.resolution
        )
        return TopicResponse.from_topic(topic)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/topics/{topic_id}", response_model=TopicResponse)
async def get_topic(
    topic_id: str,
    manager: TopicManager = Depends(get_topic_manager)
):
    """Get a specific topic."""
    topic = manager.get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail=f"Topic '{topic_id}' not found")
    return TopicResponse.from_topic(topic)


@router.delete("/topics/{topic_id}", status_code=204)
async def delete_topic(
    topic_id: str,
    manager: TopicManager = Depends(get_topic_manager)
):
    """Stop watching a topic."""
    if not manager.remove_topic(topic_id):
        raise HTTPException(status_code=404, detail=f"Topic '{topic_id}' not found")


@router.post("/topics/{topic_id}/pause", response_model=TopicResponse)
async def pause_topic(
    topic_id: str,
    manager: TopicManager = Depends(get_topic_manager)
):
    """Pause polling for a topic."""
    if not manager.pause_topic(topic_id):
        raise HTTPException(status_code=404, detail=f"Topic '{topic_id}' not found")
    
    topic = manager.get_topic(topic_id)
    return TopicResponse.from_topic(topic)


@router.post("/topics/{topic_id}/resume", response_model=TopicResponse)
async def resume_topic(
    topic_id: str,
    manager: TopicManager = Depends(get_topic_manager)
):
    """Resume polling for a topic."""
    if not manager.resume_topic(topic_id):
        raise HTTPException(status_code=404, detail=f"Topic '{topic_id}' not found")
    
    topic = manager.get_topic(topic_id)
    return TopicResponse.from_topic(topic)


class SetResolutionRequest(BaseModel):
    """Request to change default resolution."""
    resolution: str = Field(description=f"New default resolution. Options: {list(RESOLUTION_MAP.keys())}")


@router.patch("/topics/{topic_id}/resolution", response_model=TopicResponse)
async def set_topic_resolution(
    topic_id: str,
    request: SetResolutionRequest,
    manager: TopicManager = Depends(get_topic_manager)
):
    """
    Change the default display resolution for a topic.
    
    This only changes the default - you can always query bars at any resolution
    using the ?resolution= query parameter.
    """
    if request.resolution not in RESOLUTION_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid resolution: {request.resolution}. Valid options: {list(RESOLUTION_MAP.keys())}"
        )
    
    if not manager.set_topic_resolution(topic_id, request.resolution):
        raise HTTPException(status_code=404, detail=f"Topic '{topic_id}' not found")
    
    topic = manager.get_topic(topic_id)
    return TopicResponse.from_topic(topic)


# ----------------------------------------------------------------------------
# Resolutions
# ----------------------------------------------------------------------------

@router.get("/resolutions")
async def list_resolutions():
    """
    List all available bar resolutions.
    
    Bars can be generated on-demand at any of these resolutions.
    """
    return {
        "resolutions": list(RESOLUTION_MAP.keys()),
        "default": DEFAULT_RESOLUTION,
        "details": {k: f"{v} seconds" for k, v in RESOLUTION_MAP.items()}
    }


# ----------------------------------------------------------------------------
# Bars
# ----------------------------------------------------------------------------

@router.get("/topics/{topic_id}/bars", response_model=List[BarResponse])
async def get_bars(
    topic_id: str,
    limit: int = Query(default=50, ge=1, le=500, description="Number of bars to return"),
    resolution: Optional[str] = Query(default=None, description=f"Display resolution. Options: {list(RESOLUTION_MAP.keys())}"),
    generate_summaries: bool = Query(default=True, description="Generate Grok summaries for bars"),
    manager: TopicManager = Depends(get_topic_manager)
):
    """
    Get bar timeline for a topic at any resolution.
    
    Bars are generated ON-DEMAND from raw ticks at the specified resolution.
    Each bar gets its own fresh Grok summary from the underlying ticks.
    
    This allows instant switching between resolutions (15s, 1m, 5m, etc.)
    without losing data quality.
    """
    topic = manager.get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail=f"Topic '{topic_id}' not found")
    
    # Validate resolution
    if resolution and resolution not in RESOLUTION_MAP:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid resolution: {resolution}. Valid options: {list(RESOLUTION_MAP.keys())}"
        )
    
    # Use async version to avoid blocking event loop during Grok calls
    bars = await manager.get_bars_async(
        topic_id, 
        limit=limit, 
        resolution=resolution, 
        generate_summaries=generate_summaries
    )
    return [BarResponse.from_bar(b) for b in bars]


@router.get("/topics/{topic_id}/bars/latest", response_model=Optional[BarResponse])
async def get_latest_bar(
    topic_id: str,
    resolution: Optional[str] = Query(default=None, description="Display resolution"),
    generate_summary: bool = Query(default=True, description="Generate Grok summary"),
    manager: TopicManager = Depends(get_topic_manager)
):
    """Get the most recent bar for a topic at the specified resolution."""
    topic = manager.get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail=f"Topic '{topic_id}' not found")
    
    if resolution and resolution not in RESOLUTION_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid resolution: {resolution}. Valid options: {list(RESOLUTION_MAP.keys())}"
        )
    
    # Use async version to avoid blocking event loop during Grok calls
    bar = await manager.get_latest_bar_async(
        topic_id, 
        resolution=resolution, 
        generate_summary=generate_summary
    )
    if not bar:
        return None
    return BarResponse.from_bar(bar)


# ----------------------------------------------------------------------------
# Polling (manual trigger)
# ----------------------------------------------------------------------------

@router.post("/topics/{topic_id}/poll", response_model=PollResponse)
async def poll_topic(
    topic_id: str,
    manager: TopicManager = Depends(get_topic_manager)
):
    """
    Manually trigger a poll for a topic.
    
    Fetches new ticks from X API and stores them.
    Bars are generated on-demand via GET /topics/{id}/bars?resolution=...
    """
    topic = manager.get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail=f"Topic '{topic_id}' not found")
    
    try:
        new_ticks = await manager.poll_topic(topic_id)
        total_ticks = manager.get_tick_count(topic_id)
        
        return PollResponse(
            success=True,
            message=f"Added {new_ticks} new ticks" if new_ticks > 0 else "No new ticks",
            new_ticks=new_ticks,
            total_ticks=total_ticks
        )
    except Exception as e:
        return PollResponse(
            success=False,
            message=str(e)
        )


@router.post("/poll", response_model=dict)
async def poll_all_topics(poller: TickPoller = Depends(get_tick_poller)):
    """Manually trigger a poll for all active topics."""
    await poller.poll_now()
    return {"status": "polling triggered"}


# ----------------------------------------------------------------------------
# Backfill (historical bars with summaries)
# ----------------------------------------------------------------------------

class BackfillRequest(BaseModel):
    """Request for backfilling historical bars."""
    resolution: str = Field(default="1h", description="Resolution for bars (e.g., '15s', '1m', '1h')")
    count: int = Field(default=5, ge=1, le=100, description="Number of bars to generate")
    generate_summaries: bool = Field(default=True, description="Generate Grok summaries (slower)")
    poll_first: bool = Field(default=True, description="Poll for new ticks before generating bars")


class BackfillResponse(BaseModel):
    """Response from backfill operation."""
    success: bool
    message: str
    bars_generated: int = 0
    bars_with_summaries: int = 0
    bars_with_posts: int = 0
    total_posts: int = 0
    ticks_collected: int = 0
    resolution: str = ""
    time_range: Optional[str] = None


@router.post("/topics/{topic_id}/backfill", response_model=BackfillResponse)
async def backfill_bars(
    topic_id: str,
    request: BackfillRequest,
    manager: TopicManager = Depends(get_topic_manager)
):
    """
    🕐 Generate historical bars with summaries (on-demand, slower).
    
    Use this to backfill bars when you need historical data with summaries,
    e.g., on startup to get the last 5 hourly summaries.
    
    This bypasses the normal fast BarStore route and generates fresh bars
    with Grok summaries for each.
    
    **Note**: This is slower than normal GET /bars because it calls Grok
    for each bar's summary. Use for initial data load, not real-time.
    
    Example:
        POST /topics/bitcoin/backfill
        {"resolution": "1h", "count": 5, "generate_summaries": true}
    """
    topic = manager.get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail=f"Topic '{topic_id}' not found")
    
    if request.resolution not in RESOLUTION_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid resolution: {request.resolution}. Valid: {list(RESOLUTION_MAP.keys())}"
        )
    
    try:
        # Optionally poll for new ticks first
        ticks_before = manager.tick_store.get_tick_count(topic.label)
        
        if request.poll_first:
            # Poll multiple times to collect more data
            for _ in range(3):
                await manager.poll_topic(topic_id)
        
        ticks_after = manager.tick_store.get_tick_count(topic.label)
        
        # Warn if no ticks
        if ticks_after == 0:
            return BackfillResponse(
                success=False,
                message="No ticks available. Poll the topic first to collect data, then backfill.",
                resolution=request.resolution
            )
        
        # Get tick time range to generate bars that actually have data
        tick_range = manager.tick_store.get_time_range(topic.label)
        if not tick_range:
            return BackfillResponse(
                success=False,
                message="No tick time range available",
                resolution=request.resolution
            )
        
        oldest_tick, newest_tick = tick_range
        resolution_seconds = RESOLUTION_MAP[request.resolution]
        
        # Calculate how many bars can have data based on tick time span
        tick_span_seconds = (newest_tick - oldest_tick).total_seconds()
        max_bars_with_data = max(1, int(tick_span_seconds / resolution_seconds) + 1)
        
        # Limit count to bars that can actually have data
        effective_count = min(request.count, max_bars_with_data)
        
        # Generate bars ending AFTER the newest tick
        from datetime import timedelta
        end_time = newest_tick + timedelta(seconds=resolution_seconds)
        
        # Generate bars directly from tick data (bypassing BarStore cache)
        bars = await manager.bar_generator.generate_bars_async(
            topic=topic.label,
            resolution=request.resolution,
            limit=effective_count,
            generate_summaries=request.generate_summaries,
            end_time=end_time
        )
        
        # Store in BarStore for future fast access
        for bar in bars:
            await manager.bar_store.add_bar(bar)
        
        bars_with_summaries = sum(1 for b in bars if b.summary is not None)
        bars_with_posts = sum(1 for b in bars if b.post_count > 0)
        total_posts = sum(b.post_count for b in bars)
        
        # Calculate time range
        if bars:
            oldest = bars[-1].start.strftime('%Y-%m-%d %H:%M')
            newest = bars[0].end.strftime('%Y-%m-%d %H:%M')
            time_range = f"{oldest} to {newest}"
        else:
            time_range = None
        
        # Build message with info about limiting
        msg = f"Generated {len(bars)} {request.resolution} bars ({bars_with_posts} with posts, {bars_with_summaries} with summaries)"
        if effective_count < request.count:
            msg += f" [limited from {request.count} to {effective_count} based on tick data span]"
        
        return BackfillResponse(
            success=True,
            message=msg,
            bars_generated=len(bars),
            bars_with_summaries=bars_with_summaries,
            bars_with_posts=bars_with_posts,
            total_posts=total_posts,
            ticks_collected=ticks_after - ticks_before if request.poll_first else 0,
            resolution=request.resolution,
            time_range=time_range
        )
        
    except Exception as e:
        logger.error(f"Backfill failed for {topic_id}: {e}")
        return BackfillResponse(
            success=False,
            message=str(e),
            resolution=request.resolution
        )


# ----------------------------------------------------------------------------
# Digest
# ----------------------------------------------------------------------------

@router.post("/topics/{topic_id}/digest", response_model=DigestResponse)
async def create_digest(
    topic_id: str,
    lookback_bars: int = Query(default=12, ge=1, le=100, description="Number of bars to include"),
    manager: TopicManager = Depends(get_topic_manager),
    digest_service: DigestService = Depends(get_digest_service)
):
    """
    Generate a digest for a topic based on recent bars.
    """
    topic = manager.get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail=f"Topic '{topic_id}' not found")
    
    # Get bars from TopicManager (use async to avoid blocking)
    bars = await manager.get_bars_async(topic_id, limit=lookback_bars, generate_summaries=True)
    
    try:
        digest = await digest_service.create_digest_async(
            topic=topic.label,
            bars=bars,
            lookback_bars=lookback_bars
        )
        
        return DigestResponse(
            topic=digest.topic,
            generated_at=digest.generated_at,
            time_range=digest.time_range,
            overall_summary=digest.overall_summary,
            key_developments=digest.key_developments,
            trending_elements=digest.trending_elements,
            sentiment_trend=digest.sentiment_trend,
            recommendations=digest.recommendations
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate digest: {e}")


# ----------------------------------------------------------------------------
# Location & Trending Topics
# ----------------------------------------------------------------------------

@router.get("/locations", response_model=LocationListResponse, tags=["Trending"])
async def list_locations(location_service = Depends(get_location_service)):
    """
    List all available locations with WOEID mapping.

    Returns a list of cities that can be used to fetch trending topics.
    """
    locations = location_service.list_available_locations()
    return LocationListResponse(locations=locations)


@router.post("/location/resolve", response_model=WOEIDResponse, tags=["Trending"])
async def resolve_location(
    request: LocationRequest,
    location_service = Depends(get_location_service)
):
    """
    Resolve a user location (coordinates or IP) to a WOEID.

    Supports:
    - GPS coordinates (latitude, longitude)
    - IP address (automatic geolocation)
    - Use ip_address="auto" to extract IP from the request

    Returns the nearest city WOEID for fetching trending topics.
    """
    from fastapi import Request as FastAPIRequest

    # Handle coordinates
    if request.latitude is not None and request.longitude is not None:
        try:
            result = location_service.resolve_woeid_from_coordinates(
                request.latitude,
                request.longitude
            )
            return WOEIDResponse(
                woeid=result.woeid,
                location_name=result.location_name,
                country=result.country,
                source="coordinates",
                latitude=result.latitude,
                longitude=result.longitude
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid coordinates: {e}")

    # Handle IP address
    elif request.ip_address:
        # Note: In production, you'd extract the real client IP from request headers
        # For now, we'll use a placeholder
        ip = request.ip_address if request.ip_address != "auto" else "8.8.8.8"

        try:
            result = location_service.resolve_woeid_from_ip(ip)
            return WOEIDResponse(
                woeid=result.woeid,
                location_name=result.location_name,
                country=result.country,
                source="ip",
                latitude=result.latitude,
                longitude=result.longitude
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"IP geolocation failed: {e}")

    else:
        raise HTTPException(
            status_code=400,
            detail="Must provide either (latitude, longitude) or ip_address"
        )


@router.get("/trends/{woeid}", response_model=TrendingTopicsResponse, tags=["Trending"])
async def get_trending_topics(
    woeid: int,
    limit: int = Query(default=10, ge=1, le=50, description="Number of trends to return"),
    location_service = Depends(get_location_service),
    trends_cache = Depends(get_trends_cache),
    x_adapter = Depends(get_x_adapter)
):
    """
    Get trending topics for a specific WOEID.

    Results are cached for 15 minutes to ensure fast responses and reduce API calls.

    Use GET /locations to see available WOEIDs, or use WOEID 1 for Worldwide.
    """
    # Check cache first
    cached_trends = trends_cache.get(woeid)
    if cached_trends:
        metadata = trends_cache.get_metadata(woeid)

        # Get location name
        location_name = "Unknown"
        country = "Unknown"
        for loc_name, loc_data in location_service.WOEID_MAP.items():
            if loc_data["woeid"] == woeid:
                location_name = loc_name
                country = loc_data["country"]
                break

        return TrendingTopicsResponse(
            woeid=woeid,
            location_name=location_name,
            country=country,
            trends=[TrendingTopic(**t) for t in cached_trends[:limit]],
            cached=True,
            cached_at=metadata["cached_at"],
            expires_at=metadata["expires_at"]
        )

    # Fetch from X API
    try:
        trends = x_adapter.get_trending_topics(woeid, limit=limit)

        # Cache the results
        trends_cache.set(woeid, trends)

        # Get location name
        location_name = "Unknown"
        country = "Unknown"
        for loc_name, loc_data in location_service.WOEID_MAP.items():
            if loc_data["woeid"] == woeid:
                location_name = loc_name
                country = loc_data["country"]
                break

        metadata = trends_cache.get_metadata(woeid)

        return TrendingTopicsResponse(
            woeid=woeid,
            location_name=location_name,
            country=country,
            trends=[TrendingTopic(**t) for t in trends],
            cached=False,
            cached_at=metadata["cached_at"] if metadata else None,
            expires_at=metadata["expires_at"] if metadata else None
        )

    except Exception as e:
        # Try to return stale cache as fallback
        stale_trends = trends_cache.get(woeid, allow_stale=True)
        if stale_trends:
            logger.warning(f"Returning stale cache for WOEID {woeid} due to error: {e}")

            location_name = "Unknown"
            country = "Unknown"
            for loc_name, loc_data in location_service.WOEID_MAP.items():
                if loc_data["woeid"] == woeid:
                    location_name = loc_name
                    country = loc_data["country"]
                    break

            metadata = trends_cache.get_metadata(woeid)

            return TrendingTopicsResponse(
                woeid=woeid,
                location_name=location_name,
                country=country,
                trends=[TrendingTopic(**t) for t in stale_trends[:limit]],
                cached=True,
                cached_at=metadata["cached_at"] if metadata else None,
                expires_at=metadata["expires_at"] if metadata else None
            )

        # No cache available, raise error
        raise HTTPException(status_code=500, detail=f"Failed to fetch trending topics: {e}")


@router.post("/trends/for-location", response_model=TrendingTopicsResponse, tags=["Trending"])
async def get_trends_for_location(
    request: LocationRequest,
    limit: int = Query(default=10, ge=1, le=50, description="Number of trends to return"),
    location_service = Depends(get_location_service),
    trends_cache = Depends(get_trends_cache),
    x_adapter = Depends(get_x_adapter)
):
    """
    Combined endpoint: resolve location and fetch trending topics.

    This is the primary frontend endpoint. It:
    1. Resolves your location (coordinates or IP) to a WOEID
    2. Fetches trending topics for that WOEID (with caching)

    Supports:
    - GPS coordinates (latitude, longitude)
    - IP address (ip_address="auto" to use request IP)
    - Fallback to Worldwide if location detection fails
    """
    # Resolve location to WOEID
    woeid = 1  # Default to Worldwide
    location_name = "Worldwide"
    country = "Global"

    try:
        if request.latitude is not None and request.longitude is not None:
            result = location_service.resolve_woeid_from_coordinates(
                request.latitude,
                request.longitude
            )
            woeid = result.woeid
            location_name = result.location_name
            country = result.country
        elif request.ip_address:
            ip = request.ip_address if request.ip_address != "auto" else "8.8.8.8"
            result = location_service.resolve_woeid_from_ip(ip)
            woeid = result.woeid
            location_name = result.location_name
            country = result.country
    except Exception as e:
        logger.warning(f"Location resolution failed, using Worldwide: {e}")
        # Continue with default Worldwide WOEID

    # Fetch trending topics (reuse logic from get_trending_topics)
    cached_trends = trends_cache.get(woeid)
    if cached_trends:
        metadata = trends_cache.get_metadata(woeid)
        return TrendingTopicsResponse(
            woeid=woeid,
            location_name=location_name,
            country=country,
            trends=[TrendingTopic(**t) for t in cached_trends[:limit]],
            cached=True,
            cached_at=metadata["cached_at"],
            expires_at=metadata["expires_at"]
        )

    # Fetch from X API
    try:
        trends = x_adapter.get_trending_topics(woeid, limit=limit)
        trends_cache.set(woeid, trends)
        metadata = trends_cache.get_metadata(woeid)

        return TrendingTopicsResponse(
            woeid=woeid,
            location_name=location_name,
            country=country,
            trends=[TrendingTopic(**t) for t in trends],
            cached=False,
            cached_at=metadata["cached_at"] if metadata else None,
            expires_at=metadata["expires_at"] if metadata else None
        )

    except Exception as e:
        # Try stale cache
        stale_trends = trends_cache.get(woeid, allow_stale=True)
        if stale_trends:
            logger.warning(f"Returning stale cache for WOEID {woeid}: {e}")
            metadata = trends_cache.get_metadata(woeid)
            return TrendingTopicsResponse(
                woeid=woeid,
                location_name=location_name,
                country=country,
                trends=[TrendingTopic(**t) for t in stale_trends[:limit]],
                cached=True,
                cached_at=metadata["cached_at"] if metadata else None,
                expires_at=metadata["expires_at"] if metadata else None
            )

        raise HTTPException(status_code=500, detail=f"Failed to fetch trending topics: {e}")


# ============================================================================
# Monitoring & Observability
# ============================================================================

# Store rate limiter reference for monitoring
_rate_limiter = None

def set_rate_limiter(rate_limiter):
    """Set the rate limiter for monitoring."""
    global _rate_limiter
    _rate_limiter = rate_limiter


@router.get("/monitor/dashboard", tags=["Monitoring"])
async def get_dashboard():
    """
    📊 Full monitoring dashboard data.
    
    Returns all metrics, health status, and recent activity in one call.
    Perfect for a monitoring UI.
    """
    return monitor.get_dashboard_data()


@router.get("/monitor/health", tags=["Monitoring"])
async def get_system_health():
    """
    🏥 System health check with component status.
    
    Returns overall health and per-component breakdown.
    """
    return monitor.get_health_status()


@router.get("/monitor/metrics", tags=["Monitoring"])
async def get_metrics():
    """
    📈 Detailed performance metrics.
    
    Includes:
    - Request counts and latencies
    - Cache hit rates
    - API call statistics
    - Data pipeline throughput
    """
    return monitor.metrics.get_metrics()


@router.get("/monitor/rate-limits", tags=["Monitoring"])
async def get_rate_limits():
    """
    ⏱️ API rate limit status.
    
    Shows current usage vs limits for:
    - X API (search, user lookup)
    - Grok API (fast model, reasoning model)
    """
    if _rate_limiter is None:
        return {"error": "Rate limiter not configured", "categories": {}}
    
    status = get_rate_limit_status(_rate_limiter)
    
    # Add visual indicators
    for category, info in status.items():
        if info["status"] == "critical":
            info["emoji"] = "🔴"
        elif info["status"] == "warning":
            info["emoji"] = "🟡"
        else:
            info["emoji"] = "🟢"
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "categories": status,
        "summary": {
            "total_categories": len(status),
            "critical": sum(1 for s in status.values() if s["status"] == "critical"),
            "warning": sum(1 for s in status.values() if s["status"] == "warning"),
            "ok": sum(1 for s in status.values() if s["status"] == "ok"),
        }
    }


@router.get("/monitor/activity", tags=["Monitoring"])
async def get_activity_feed(
    limit: int = Query(default=50, ge=1, le=200, description="Number of events"),
    event_type: Optional[str] = Query(default=None, description="Filter by event type")
):
    """
    📜 Real-time activity feed.
    
    Recent system events including:
    - Polls and tick additions
    - Bar generations
    - Cache hits/misses
    - Errors and warnings
    """
    # Parse event type if provided
    filter_type = None
    if event_type:
        try:
            filter_type = EventType(event_type)
        except ValueError:
            valid_types = [e.value for e in EventType]
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid event_type. Valid options: {valid_types}"
            )
    
    events = monitor.activity.get_recent(limit=limit, event_type=filter_type)
    event_counts = monitor.activity.get_event_counts(since_minutes=5)
    
    return {
        "events": events,
        "event_counts_5m": event_counts,
        "available_types": [e.value for e in EventType],
    }


@router.get("/monitor/topics", tags=["Monitoring"])
async def get_topics_status(manager: TopicManager = Depends(get_topic_manager)):
    """
    📋 Detailed topic status and statistics.
    
    Per-topic breakdown including:
    - Tick counts and data freshness
    - Poll history
    - Error status
    """
    topics = manager.list_topics()
    
    topic_stats = []
    for topic in topics:
        # Calculate data freshness
        freshness = None
        if topic.last_poll:
            age = (datetime.now(timezone.utc) - topic.last_poll).total_seconds()
            freshness = {
                "seconds_ago": int(age),
                "status": "fresh" if age < 60 else ("stale" if age < 300 else "very_stale"),
                "emoji": "🟢" if age < 60 else ("🟡" if age < 300 else "🔴"),
            }
        
        topic_stats.append({
            "id": topic.id,
            "label": topic.label,
            "status": topic.status.value,
            "status_emoji": "✅" if topic.status == TopicStatus.ACTIVE else ("⏸️" if topic.status == TopicStatus.PAUSED else "❌"),
            "resolution": topic.resolution,
            "tick_count": topic.tick_count,
            "poll_count": topic.poll_count,
            "last_poll": topic.last_poll.isoformat() if topic.last_poll else None,
            "data_freshness": freshness,
            "last_error": topic.last_error,
            "created_at": topic.created_at.isoformat(),
        })
    
    # Summary stats
    active = sum(1 for t in topics if t.status == TopicStatus.ACTIVE)
    total_ticks = sum(t.tick_count for t in topics)
    
    return {
        "summary": {
            "total_topics": len(topics),
            "active": active,
            "paused": sum(1 for t in topics if t.status == TopicStatus.PAUSED),
            "error": sum(1 for t in topics if t.status == TopicStatus.ERROR),
            "total_ticks": total_ticks,
        },
        "topics": topic_stats,
    }


@router.get("/debug/ticks/{topic_id}", tags=["Debug"])
async def get_tick_debug(
    topic_id: str,
    limit: int = Query(default=10, ge=1, le=100),
    start: Optional[str] = Query(default=None, description="Start time ISO format"),
    end: Optional[str] = Query(default=None, description="End time ISO format"),
    manager: TopicManager = Depends(get_topic_manager)
):
    """Debug endpoint to inspect tick timestamps."""
    from datetime import datetime, timezone
    
    topic = manager.get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail=f"Topic '{topic_id}' not found")
    
    # Parse optional time filters
    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00')) if start else None
    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00')) if end else None
    
    # Get all ticks for this topic (with optional time filter)
    ticks = manager.tick_store.get_ticks(topic.label, start=start_dt, end=end_dt)
    time_range = manager.tick_store.get_time_range(topic.label)
    
    return {
        "topic_id": topic_id,
        "topic_label": topic.label,
        "query_start": start,
        "query_end": end,
        "total_ticks_in_range": len(ticks),
        "total_ticks_all": manager.tick_store.get_tick_count(topic.label),
        "time_range": {
            "oldest": time_range[0].isoformat() if time_range else None,
            "newest": time_range[1].isoformat() if time_range else None,
        },
        "sample_ticks": [
            {
                "id": t.id,
                "timestamp": t.timestamp.isoformat(),
                "author": t.author,
                "topic": t.topic,
            }
            for t in ticks[-limit:]  # Most recent ticks
        ]
    }


@router.get("/monitor/live-stats", tags=["Monitoring"])
async def get_live_stats(manager: TopicManager = Depends(get_topic_manager)):
    """
    ⚡ Live statistics for real-time display.
    
    Lightweight endpoint optimized for frequent polling.
    Returns key metrics only.
    """
    metrics = monitor.metrics.get_metrics()
    topics = manager.list_topics()
    
    active_topics = [t for t in topics if t.status == TopicStatus.ACTIVE]
    total_ticks = sum(t.tick_count for t in topics)
    
    # Get rate limit summary
    rate_limit_status = "ok"
    if _rate_limiter:
        statuses = get_rate_limit_status(_rate_limiter)
        if any(s["status"] == "critical" for s in statuses.values()):
            rate_limit_status = "critical"
        elif any(s["status"] == "warning" for s in statuses.values()):
            rate_limit_status = "warning"
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime": metrics["uptime_human"],
        "topics_active": len(active_topics),
        "total_ticks": total_ticks,
        "ticks_per_minute": round(metrics["data_pipeline"]["ticks_per_minute"], 1),
        "rate_limit_status": rate_limit_status,
        "grok_calls": metrics["grok_api"]["calls"],
        "x_api_calls": metrics["x_api"]["calls"],
    }


__all__ = ["router", "set_dependencies", "set_location_dependencies", "set_rate_limiter"]

