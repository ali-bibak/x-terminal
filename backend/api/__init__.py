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
    sentiment: Optional[str]
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


# ============================================================================
# Dependency Injection - these get set by the main app
# ============================================================================

_topic_manager: Optional[TopicManager] = None
_tick_poller: Optional[TickPoller] = None
_digest_service: Optional[DigestService] = None


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
    
    bars = manager.get_bars(topic_id, limit=limit, resolution=resolution, generate_summaries=generate_summaries)
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
    
    bar = manager.get_latest_bar(topic_id, resolution=resolution, generate_summary=generate_summary)
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
    
    # Get bars from TopicManager (where they're actually stored)
    bars = manager.get_bars(topic_id, limit=lookback_bars)
    
    try:
        digest = digest_service.create_digest(
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
        "cache_hit_rate": metrics["cache"]["hit_rate"],
        "rate_limit_status": rate_limit_status,
        "grok_calls": metrics["grok_api"]["calls"],
        "x_api_calls": metrics["x_api"]["calls"],
    }


__all__ = ["router", "set_dependencies", "set_rate_limiter"]

