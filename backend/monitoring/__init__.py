"""
Monitoring and observability module for X Terminal.

Provides real-time metrics and insights for:
- System health
- API rate limits (X API, Grok API)
- Data pipeline status
- Performance metrics
- Activity feed
"""

from __future__ import annotations

import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from collections import deque
from enum import Enum

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Types of system events."""
    POLL = "poll"
    TICK_ADDED = "tick_added"
    BAR_GENERATED = "bar_generated"
    SUMMARY_CACHED = "summary_cached"
    SUMMARY_CACHE_HIT = "summary_cache_hit"
    RATE_LIMIT_WARNING = "rate_limit_warning"
    ERROR = "error"
    TOPIC_ADDED = "topic_added"
    TOPIC_REMOVED = "topic_removed"


@dataclass
class SystemEvent:
    """A recorded system event."""
    timestamp: datetime
    event_type: EventType
    topic: Optional[str]
    details: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
            "topic": self.topic,
            "details": self.details,
            "age_seconds": (datetime.now(timezone.utc) - self.timestamp).total_seconds()
        }


class MetricsCollector:
    """
    Collects and aggregates system metrics.
    
    Tracks:
    - Request counts per endpoint
    - Latency distributions
    - Error rates
    - Cache performance
    """
    
    def __init__(self):
        self._start_time = time.time()
        self._request_counts: Dict[str, int] = {}
        self._latencies: Dict[str, List[float]] = {}
        self._error_counts: Dict[str, int] = {}
        
        # Cache metrics
        self._cache_hits = 0
        self._cache_misses = 0
        
        # Grok API metrics
        self._grok_calls = 0
        self._grok_errors = 0
        self._grok_latencies: List[float] = []
        
        # X API metrics  
        self._x_api_calls = 0
        self._x_api_errors = 0
        self._x_api_latencies: List[float] = []
        
        # Tick/Bar metrics
        self._ticks_processed = 0
        self._bars_generated = 0
    
    def record_request(self, endpoint: str, latency_ms: float, error: bool = False) -> None:
        """Record an API request."""
        self._request_counts[endpoint] = self._request_counts.get(endpoint, 0) + 1
        
        if endpoint not in self._latencies:
            self._latencies[endpoint] = []
        self._latencies[endpoint].append(latency_ms)
        
        # Keep only last 1000 latencies per endpoint
        if len(self._latencies[endpoint]) > 1000:
            self._latencies[endpoint] = self._latencies[endpoint][-1000:]
        
        if error:
            self._error_counts[endpoint] = self._error_counts.get(endpoint, 0) + 1
    
    def record_cache_hit(self) -> None:
        """Record a cache hit."""
        self._cache_hits += 1
    
    def record_cache_miss(self) -> None:
        """Record a cache miss."""
        self._cache_misses += 1
    
    def record_grok_call(self, latency_ms: float, error: bool = False) -> None:
        """Record a Grok API call."""
        self._grok_calls += 1
        self._grok_latencies.append(latency_ms)
        if len(self._grok_latencies) > 1000:
            self._grok_latencies = self._grok_latencies[-1000:]
        if error:
            self._grok_errors += 1
    
    def record_x_api_call(self, latency_ms: float, error: bool = False) -> None:
        """Record an X API call."""
        self._x_api_calls += 1
        self._x_api_latencies.append(latency_ms)
        if len(self._x_api_latencies) > 1000:
            self._x_api_latencies = self._x_api_latencies[-1000:]
        if error:
            self._x_api_errors += 1
    
    def record_ticks(self, count: int) -> None:
        """Record ticks processed."""
        self._ticks_processed += count
    
    def record_bar_generated(self) -> None:
        """Record a bar generation."""
        self._bars_generated += 1
    
    def _calculate_percentiles(self, values: List[float]) -> Dict[str, float]:
        """Calculate p50, p95, p99 percentiles."""
        if not values:
            return {"p50": 0, "p95": 0, "p99": 0, "avg": 0}
        
        sorted_values = sorted(values)
        n = len(sorted_values)
        
        return {
            "p50": sorted_values[int(n * 0.50)] if n > 0 else 0,
            "p95": sorted_values[int(n * 0.95)] if n > 0 else 0,
            "p99": sorted_values[int(n * 0.99)] if n > 0 else 0,
            "avg": sum(values) / n if n > 0 else 0,
        }
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get all collected metrics."""
        uptime = time.time() - self._start_time
        
        # Calculate cache hit rate
        total_cache = self._cache_hits + self._cache_misses
        cache_hit_rate = self._cache_hits / total_cache if total_cache > 0 else 0
        
        # Calculate error rates
        grok_error_rate = self._grok_errors / self._grok_calls if self._grok_calls > 0 else 0
        x_api_error_rate = self._x_api_errors / self._x_api_calls if self._x_api_calls > 0 else 0
        
        return {
            "uptime_seconds": int(uptime),
            "uptime_human": self._format_duration(uptime),
            
            "requests": {
                "total": sum(self._request_counts.values()),
                "by_endpoint": self._request_counts,
                "errors": self._error_counts,
            },
            
            "cache": {
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "hit_rate": f"{cache_hit_rate:.1%}",
            },
            
            "grok_api": {
                "calls": self._grok_calls,
                "errors": self._grok_errors,
                "error_rate": f"{grok_error_rate:.1%}",
                "latency_ms": self._calculate_percentiles(self._grok_latencies),
            },
            
            "x_api": {
                "calls": self._x_api_calls,
                "errors": self._x_api_errors,
                "error_rate": f"{x_api_error_rate:.1%}",
                "latency_ms": self._calculate_percentiles(self._x_api_latencies),
            },
            
            "data_pipeline": {
                "ticks_processed": self._ticks_processed,
                "bars_generated": self._bars_generated,
                "ticks_per_minute": self._ticks_processed / (uptime / 60) if uptime > 0 else 0,
            },
        }
    
    def _format_duration(self, seconds: float) -> str:
        """Format duration as human-readable string."""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds // 60)}m {int(seconds % 60)}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"


class ActivityFeed:
    """
    Real-time activity feed for system events.
    
    Stores recent events for live monitoring.
    """
    
    def __init__(self, max_events: int = 500):
        self.max_events = max_events
        self._events: deque = deque(maxlen=max_events)
    
    def add_event(
        self, 
        event_type: EventType, 
        topic: Optional[str] = None,
        **details
    ) -> None:
        """Add an event to the feed."""
        event = SystemEvent(
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            topic=topic,
            details=details
        )
        self._events.append(event)
    
    def get_recent(self, limit: int = 50, event_type: Optional[EventType] = None) -> List[Dict]:
        """Get recent events, optionally filtered by type."""
        events = list(self._events)
        
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        
        # Return most recent first
        events = sorted(events, key=lambda e: e.timestamp, reverse=True)
        return [e.to_dict() for e in events[:limit]]
    
    def get_event_counts(self, since_minutes: int = 5) -> Dict[str, int]:
        """Get event counts by type since N minutes ago."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        
        counts: Dict[str, int] = {}
        for event in self._events:
            if event.timestamp >= cutoff:
                key = event.event_type.value
                counts[key] = counts.get(key, 0) + 1
        
        return counts


class SystemMonitor:
    """
    Central monitoring hub for X Terminal.
    
    Aggregates metrics from all components.
    """
    
    def __init__(self):
        self.metrics = MetricsCollector()
        self.activity = ActivityFeed()
        self._component_status: Dict[str, Dict[str, Any]] = {}
    
    def set_component_status(
        self, 
        component: str, 
        status: str,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Set status for a component."""
        self._component_status[component] = {
            "status": status,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "details": details or {}
        }
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get overall system health status."""
        # Determine overall status
        statuses = [c.get("status", "unknown") for c in self._component_status.values()]
        
        if all(s == "healthy" for s in statuses):
            overall = "healthy"
        elif any(s == "error" for s in statuses):
            overall = "degraded"
        elif any(s == "warning" for s in statuses):
            overall = "warning"
        else:
            overall = "unknown"
        
        return {
            "status": overall,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": self._component_status,
        }
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get all data needed for a monitoring dashboard."""
        return {
            "health": self.get_health_status(),
            "metrics": self.metrics.get_metrics(),
            "recent_activity": self.activity.get_recent(limit=20),
            "event_counts_5m": self.activity.get_event_counts(since_minutes=5),
        }


# Global monitor instance
monitor = SystemMonitor()


def get_rate_limit_status(rate_limiter) -> Dict[str, Any]:
    """
    Get detailed rate limit status from a RateLimiter instance.
    
    Args:
        rate_limiter: RateLimiter instance
    
    Returns:
        Detailed rate limit status for all configured categories
    """
    status = {}
    
    for category, config in rate_limiter.configs.items():
        remaining = rate_limiter.get_remaining_requests(category)
        used = config.requests_per_window - remaining
        usage_pct = (used / config.requests_per_window * 100) if config.requests_per_window > 0 else 0
        
        status[category] = {
            "limit": config.requests_per_window,
            "window_seconds": config.window_seconds,
            "strategy": config.strategy,
            "remaining": remaining,
            "used": used,
            "usage_percent": f"{usage_pct:.1f}%",
            "status": "ok" if usage_pct < 80 else ("warning" if usage_pct < 95 else "critical"),
        }
    
    return status


__all__ = [
    "SystemMonitor",
    "MetricsCollector", 
    "ActivityFeed",
    "EventType",
    "SystemEvent",
    "monitor",
    "get_rate_limit_status",
]

