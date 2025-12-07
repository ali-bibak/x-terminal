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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from adapter.x import XAdapter
from adapter.grok import GrokAdapter
from adapter.rate_limiter import RateLimiter
from aggregator import BarAggregator, DigestService
from core import TopicManager, TickPoller
from api import router, set_dependencies

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Global services (initialized on startup)
topic_manager: TopicManager = None
tick_poller: TickPoller = None
digest_service: DigestService = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan - setup and teardown.
    """
    global topic_manager, tick_poller, digest_service
    
    logger.info("Starting X Terminal backend...")
    
    # Initialize adapters
    rate_limiter = RateLimiter()
    
    x_adapter = XAdapter(
        bearer_token=os.environ.get("X_BEARER_TOKEN"),
        rate_limiter=rate_limiter,
        skip_rate_limit=True  # Let X API handle limiting
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
    
    # Initialize core services
    topic_manager = TopicManager(
        x_adapter=x_adapter,
        grok_adapter=grok_adapter,
        default_resolution="5m"
    )
    
    # Create a shared aggregator for digest service
    # (DigestService uses topic_manager's per-topic aggregators internally)
    shared_aggregator = BarAggregator(grok_adapter=grok_adapter)
    digest_service = DigestService(
        grok_adapter=grok_adapter,
        bar_aggregator=shared_aggregator
    )
    
    # Initialize poller (polls every 5 minutes by default)
    poll_interval = int(os.environ.get("POLL_INTERVAL", "300"))
    tick_poller = TickPoller(
        topic_manager=topic_manager,
        poll_interval=poll_interval,
        generate_summaries=True
    )
    
    # Set dependencies for API routes
    set_dependencies(topic_manager, tick_poller, digest_service)
    
    # Start background poller
    auto_poll = os.environ.get("AUTO_POLL", "false").lower() == "true"
    if auto_poll:
        await tick_poller.start()
        logger.info(f"✓ Background poller started (interval: {poll_interval}s)")
    else:
        logger.info("ℹ Background poller disabled (set AUTO_POLL=true to enable)")
    
    logger.info("X Terminal backend ready!")
    
    yield  # Application runs here
    
    # Shutdown
    logger.info("Shutting down X Terminal backend...")
    if tick_poller:
        await tick_poller.stop()
    logger.info("Goodbye!")


# Create FastAPI app
app = FastAPI(
    title="X Terminal API",
    description="LiveOps dashboard backend for X powered by Grok",
    version="1.0.0",
    lifespan=lifespan
)

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
    return {
        "name": "X Terminal API",
        "version": "1.0.0",
        "docs": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=True
    )

