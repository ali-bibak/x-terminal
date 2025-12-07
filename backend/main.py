"""
X Terminal Backend - Main FastAPI Application

Run with:
    uvicorn main:app --reload --port 8000
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from adapter.grok import GrokAdapter
from adapter.rate_limiter import RateLimiter
from adapter.x import XAdapter
from aggregator import DigestService, BarStore, MIN_RESOLUTION_SECONDS, DEFAULT_RESOLUTION
from api import router, set_dependencies, set_location_dependencies, set_rate_limiter
from core import TickPoller, TopicManager, BarScheduler
from database import init_db
from monitoring import monitor, EventType
from services import LocationService, TrendsCache

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Global services (initialized on startup)
topic_manager: TopicManager = None
tick_poller: TickPoller = None
bar_scheduler: BarScheduler = None
digest_service: DigestService = None


class RequestMonitoringMiddleware(BaseHTTPMiddleware):
    """Middleware to monitor FastAPI requests."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip monitoring for health checks and static files
        if request.url.path in ["/", "/docs", "/redoc", "/openapi.json"]:
            return await call_next(request)

        import time
        start_time = time.time()

        try:
            response = await call_next(request)
            latency_ms = (time.time() - start_time) * 1000

            # Record successful request
            mon = _get_monitor()
            if mon:
                # Normalize endpoint name (remove /api/v1 prefix)
                endpoint = request.url.path.replace("/api/v1", "") or "/"

                # Mark as error for 5xx status codes
                is_error = response.status_code >= 500
                mon.metrics.record_request(endpoint, latency_ms, error=is_error)

            return response

        except Exception as e:
            # Record failed request
            latency_ms = (time.time() - start_time) * 1000
            mon = _get_monitor()
            if mon:
                endpoint = request.url.path.replace("/api/v1", "") or "/"
                mon.metrics.record_request(endpoint, latency_ms, error=True)

            # Re-raise the exception
            raise


# Lazy import to avoid circular dependency
def _get_monitor():
    try:
        from monitoring import monitor
        return monitor
    except ImportError:
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan - setup and teardown.
    """
    global topic_manager, tick_poller, bar_scheduler, digest_service

    init_db()

    logger.info("Starting X Terminal backend...")
    # Initialize adapters
    rate_limiter = RateLimiter()
    
    # Configure Grok rate limits (generous - Grok API handles its own limits)
    from adapter.rate_limiter import RateLimitConfig
    rate_limiter.configure_limit("grok_fast", RateLimitConfig(
        requests_per_window=60,  # 60 requests per minute
        window_seconds=60,
        strategy="sliding_window"
    ))
    rate_limiter.configure_limit("grok_reasoning", RateLimitConfig(
        requests_per_window=30,  # 30 requests per minute (reasoning is slower)
        window_seconds=60,
        strategy="sliding_window"
    ))

    x_adapter = XAdapter(
        bearer_token=os.environ.get("X_BEARER_TOKEN"),
        rate_limiter=rate_limiter,
        skip_rate_limit=True,  # Let X API handle limiting
    )

    grok_adapter = GrokAdapter(rate_limiter=rate_limiter)

    # Log adapter status
    if x_adapter.is_configured:
        logger.info("✓ X Adapter configured")
    else:
        logger.warning("⚠ X Adapter not configured - set X_BEARER_TOKEN")

    if grok_adapter.is_live:
        logger.info("✓ Grok Adapter live")
    else:
        logger.warning("⚠ Grok Adapter not live - set XAI_API_KEY")

    # Initialize BarStore for pre-computed bars
    bar_store = BarStore(max_bars_per_resolution=500)

    # Initialize core services
    # TopicManager reads from BarStore for instant GET access
    topic_manager = TopicManager(
        x_adapter=x_adapter, 
        grok_adapter=grok_adapter,
        bar_store=bar_store,
        default_resolution=DEFAULT_RESOLUTION
    )

    # Initialize digest service
    digest_service = DigestService(grok_adapter=grok_adapter)

    # Initialize poller
    # Default: polls at minimum resolution (15s) for granular tick collection
    poll_interval_env = os.environ.get("POLL_INTERVAL")
    poll_interval = int(poll_interval_env) if poll_interval_env else MIN_RESOLUTION_SECONDS
    
    tick_poller = TickPoller(
        topic_manager=topic_manager,
        poll_interval=poll_interval,
    )

    # Initialize location and trends services
    cache_ttl = int(os.environ.get("TRENDS_CACHE_TTL", "900"))  # 15 min default
    trends_cache = TrendsCache(ttl_seconds=cache_ttl)
    location_service = LocationService()

    # Initialize bar scheduler
    # Generates bars periodically at each resolution and stores in BarStore
    bar_scheduler = BarScheduler(
        topic_manager=topic_manager,
        bar_store=bar_store,
        bar_generator=topic_manager.bar_generator,
    )

    # Set dependencies for API routes
    set_dependencies(topic_manager, tick_poller, digest_service)
    set_location_dependencies(location_service, trends_cache, x_adapter)
    set_rate_limiter(rate_limiter)

    # Start background cache cleanup
    asyncio.create_task(trends_cache.start_cleanup_task())

    logger.info("✓ Location service initialized")
    logger.info(f"✓ Trends cache initialized (TTL: {cache_ttl}s)")

    # Configure monitoring
    monitor.set_component_status(
        "x_adapter",
        "healthy" if x_adapter.is_configured else "warning",
        {"configured": x_adapter.is_configured}
    )
    monitor.set_component_status(
        "grok_adapter", 
        "healthy" if grok_adapter.is_live else "warning",
        {"live": grok_adapter.is_live}
    )
    monitor.set_component_status("database", "healthy", {"initialized": True})

    # Start background services
    auto_poll = os.environ.get("AUTO_POLL", "false").lower() == "true"
    if auto_poll:
        # Start tick poller (collects raw ticks from X API)
        await tick_poller.start()
        monitor.set_component_status("poller", "healthy", {"interval": poll_interval})
        logger.info(f"✓ TickPoller started (interval: {poll_interval}s)")
        
        # Start bar scheduler (generates pre-computed bars periodically)
        await bar_scheduler.start()
        monitor.set_component_status("bar_scheduler", "healthy", {
            "resolutions": bar_scheduler.resolutions
        })
        logger.info(f"✓ BarScheduler started for resolutions: {bar_scheduler.resolutions}")
        logger.info("  Bars are pre-computed and stored for instant GET access")
    else:
        monitor.set_component_status("poller", "warning", {"enabled": False})
        monitor.set_component_status("bar_scheduler", "warning", {"enabled": False})
        logger.info("ℹ Background services disabled (set AUTO_POLL=true to enable)")
        logger.info("  GET /bars will generate bars on-demand (slower)")

    # Log monitoring endpoints
    logger.info("📊 Monitoring available at /api/v1/monitor/*")
    logger.info("X Terminal backend ready!")

    yield  # Application runs here

    # Shutdown
    logger.info("Shutting down X Terminal backend...")
    if bar_scheduler:
        await bar_scheduler.stop()
    if tick_poller:
        await tick_poller.stop()
    logger.info("Goodbye!")


# Create FastAPI app
app = FastAPI(
    title="X Terminal API",
    description="LiveOps dashboard backend for X powered by Grok",
    version="1.0.0",
    lifespan=lifespan,
)

# Request monitoring middleware
app.add_middleware(RequestMonitoringMiddleware)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)


# Root endpoint
@app.get("/")
async def root():
    return {"name": "X Terminal API", "version": "1.0.0", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=True,
    )
