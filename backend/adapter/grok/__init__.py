"""
Typed helper wrapping Grok (xai-sdk) flows for the X Terminal backend.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv, find_dotenv
from pydantic import BaseModel, Field

from ..rate_limiter import RateLimiter, shared_limiter
from ..models import Tick

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

load_dotenv(find_dotenv(usecwd=True))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from xai_sdk import Client
    from xai_sdk.chat import system, user
    XAI_SDK_AVAILABLE = True
except ImportError:  # xai-sdk might not be installed in local dev
    Client = None  # type: ignore[assignment]
    XAI_SDK_AVAILABLE = False

    def system(content: str) -> str:  # type: ignore[override]
        return content

    def user(content: str) -> str:  # type: ignore[override]
        return content


class IntelSummary(BaseModel):
    handle: str = Field(description="The @handle that was analyzed")
    summary: str = Field(description="Short operator-facing summary")
    top_topics: List[str] = Field(description="Key subjects this handle talks about")
    sentiment: str = Field(description="Overall sentiment or stance")
    recent_activity: List[str] = Field(description="Bullet list of recent actions")


class FactCheckReport(BaseModel):
    url: str = Field(description="URL that was fact checked")
    verdict: str = Field(description="true / false / unclear verdict")
    rationale: str = Field(description="Why we decided on the verdict")
    confidence: str = Field(description="low / medium / high confidence level")


class DigestOverview(BaseModel):
    generated_at: datetime = Field(description="Timestamp when digest ran")
    highlights: List[str] = Field(description="Short snippets covering the situation")
    risk_outlook: str = Field(description="One paragraph describing risk posture")
    recommended_actions: List[str] = Field(description="Actionable suggestions")


# X Terminal specific models
class BarSummary(BaseModel):
    """Summary for a time-barred window of posts."""
    summary: str = Field(description="Brief summary of what happened in this time window")
    key_themes: List[str] = Field(description="Main topics or themes discussed")
    sentiment: float = Field(description="Sentiment score from 0.0 (very negative) to 1.0 (very positive), with 0.5 being neutral")
    post_count: int = Field(description="Number of posts in this bar")
    engagement_level: str = Field(description="low/medium/high engagement level")
    highlight_posts: Optional[List[str]] = Field(default=None, description="1-2 most representative post IDs from this bar")


class TopicDigest(BaseModel):
    """Digest over multiple bars for a topic."""
    topic: str = Field(description="Topic name")
    generated_at: datetime = Field(description="When this digest was generated")
    time_range: str = Field(description="Time period covered by this digest")
    overall_summary: str = Field(description="High-level summary of the topic's activity")
    key_developments: List[str] = Field(description="Major developments or changes")
    trending_elements: List[str] = Field(description="What's gaining traction")
    sentiment_trend: str = Field(description="How sentiment has evolved")
    recommendations: List[str] = Field(description="Suggested actions or monitoring points")


class GrokAdapter:
    """
    Adapter for Grok API calls with proper error handling, logging, and rate limiting.
    """

    def __init__(self, rate_limiter: Optional[RateLimiter] = None) -> None:
        self.api_key = os.getenv("XAI_API_KEY")
        self.fast_model = os.getenv("GROK_MODEL_FAST", "grok-4-1-fast")  # Updated to current fast model
        self.reasoning_model = os.getenv("GROK_MODEL_REASONING", "grok-4-1-fast-reasoning")  # Updated to current model
        self._client: Optional[Client] = None  # type: ignore[type-arg]
        self.rate_limiter = rate_limiter or shared_limiter

        if XAI_SDK_AVAILABLE and self.api_key:
            try:
                self._client = Client(api_key=self.api_key)  # type: ignore[call-arg]
                logger.info("GrokAdapter initialized with live API client")
            except Exception as e:
                logger.warning(f"Failed to initialize xAI client: {e}")
                self._client = None
        else:
            logger.warning("GrokAdapter initialized without API client (using fallbacks)")
            self._client = None

    @property
    def is_live(self) -> bool:
        return self._client is not None

    def _structured_call(self, *, model: str, system_prompt: str, user_prompt: str, schema: type[BaseModel]) -> Optional[BaseModel]:
        """
        Perform a structured chat call via xai-sdk if available.
        Includes rate limiting and proper error handling.
        """
        if not self._client:
            logger.debug("No client available, returning None")
            return None

        start_time_ms = time.time() * 1000
        
        try:
            # Apply rate limiting with appropriate category
            category = "grok_reasoning" if model == self.reasoning_model else "grok_fast"
            self.rate_limiter.wait_if_needed(category)

            logger.debug(f"Making API call to model {model} with rate limit category {category}")

            # Try the current API pattern first
            try:
                chat = self._client.chat.create(model=model)
                chat.append(system(system_prompt))
                chat.append(user(user_prompt))
                _, payload = chat.parse(schema)  # type: ignore[arg-type]
                
                latency_ms = (time.time() * 1000) - start_time_ms
                logger.debug(f"API call successful ({latency_ms:.0f}ms)")
                
                # Record successful Grok API call
                mon = _get_monitor()
                if mon:
                    mon.metrics.record_grok_call(latency_ms, error=False)
                    from monitoring import EventType
                    mon.activity.add_event(
                        EventType.GROK_CALL,
                        model=model,
                        schema=schema.__name__,
                        latency_ms=round(latency_ms, 1)
                    )
                
                return payload
            except AttributeError:
                # Fallback for potential API changes in newer versions
                logger.debug("Trying alternative API pattern")
                # If the API has changed, we might need different method calls
                # For now, fall back to the error case
                raise

        except Exception as e:
            latency_ms = (time.time() * 1000) - start_time_ms
            logger.error(f"API call failed: {e}", exc_info=True)
            
            # Record failed Grok API call
            mon = _get_monitor()
            if mon:
                mon.metrics.record_grok_call(latency_ms, error=True)
                from monitoring import EventType
                mon.activity.add_event(
                    EventType.ERROR,
                    error=f"Grok API: {str(e)[:100]}",
                    model=model
                )
            
            return None

    # ---------------------------------------------------------------------
    # Public high-level helpers
    # ---------------------------------------------------------------------

    def summarize_user(self, handle: str, recent_posts: List[str]) -> IntelSummary:
        prompt = "\n".join(recent_posts[:5]) or "No recent posts"
        payload = self._structured_call(
            model=self.fast_model,
            system_prompt="Summarize the following X account for an operator dashboard.",
            user_prompt=f"Handle: {handle}\nRecent posts:\n{prompt}",
            schema=IntelSummary,
        )
        if isinstance(payload, IntelSummary):
            return payload
        raise RuntimeError(f"Grok API call failed for summarize_user({handle}). No fallback available.")

    def fact_check(self, url: str, text: str) -> FactCheckReport:
        payload = self._structured_call(
            model=self.reasoning_model,
            system_prompt="Fact check the provided X post. Respond with a structured verdict.",
            user_prompt=f"URL: {url}\nText:\n{text}",
            schema=FactCheckReport,
        )
        if isinstance(payload, FactCheckReport):
            return payload
        raise RuntimeError(f"Grok API call failed for fact_check({url}). No fallback available.")

    def digest(self, highlights: List[str]) -> DigestOverview:
        prompt = "\n".join(f"- {item}" for item in highlights) or "No highlights yet."
        payload = self._structured_call(
            model=self.reasoning_model,
            system_prompt="Produce an executive digest for a social-ops dashboard.",
            user_prompt=prompt,
            schema=DigestOverview,
        )
        if isinstance(payload, DigestOverview):
            return payload
        raise RuntimeError(f"Grok API call failed for digest(). No fallback available.")

    # ---------------------------------------------------------------------
    # X Terminal specific methods
    # ---------------------------------------------------------------------

    def summarize_bar(self, topic: str, ticks: List[Tick], start_time: datetime, end_time: datetime) -> BarSummary:
        """
        Generate a summary for a time-barred window of posts.
        Uses fast model for quick, structured summaries.
        """
        if not ticks:
            return BarSummary(
                summary="No posts in this time window",
                key_themes=[],
                sentiment=0.5,  # Neutral
                post_count=0,
                engagement_level="low"
            )

        # Select 1-2 highlight posts (prioritize by engagement, then recency)
        highlight_posts = self._select_highlight_posts(ticks)

        # Create a readable representation of the posts
        posts_text = "\n".join([
            f"@{tick.author}: {tick.text[:200]}..."
            for tick in ticks[:10]  # Limit to first 10 posts for summary
        ])

        # Calculate how recent this window is
        now = datetime.now(timezone.utc)
        minutes_ago = int((now - end_time).total_seconds() / 60)
        recency = f"{minutes_ago} minutes ago" if minutes_ago > 0 else "just now"
        
        # Format with date, time, and timezone
        time_range = f"{start_time.strftime('%Y-%m-%d %H:%M')}-{end_time.strftime('%H:%M')} UTC"

        user_prompt = f"""Topic: {topic}
Current time: {now.strftime('%Y-%m-%d %H:%M')} UTC
Time Window: {time_range} ({recency})
Posts ({len(ticks)} total):

{posts_text}

{"... and " + str(len(ticks) - 10) + " more posts" if len(ticks) > 10 else ""}"""

        payload = self._structured_call(
            model=self.fast_model,
            system_prompt="""You are summarizing a time window of social media posts for a live monitoring dashboard.
Create a brief, structured summary focused on what happened in this specific time window.""",
            user_prompt=user_prompt,
            schema=BarSummary,
        )

        if isinstance(payload, BarSummary):
            # Ensure post_count matches actual data and add highlight posts
            payload.post_count = len(ticks)
            payload.highlight_posts = highlight_posts
            return payload

        raise RuntimeError(f"Grok API call failed for summarize_bar({topic}). No fallback available.")

    def _select_highlight_posts(self, ticks: List[Tick]) -> Optional[List[str]]:
        """
        Select 1-2 most representative posts from the tick list.
        Prioritizes by engagement metrics, then by recency.
        """
        if len(ticks) <= 2:
            # If 2 or fewer posts, include all of them
            return [tick.id for tick in ticks]

        # Calculate engagement score for each tick
        def calculate_engagement(tick: Tick) -> int:
            metrics = tick.metrics
            return (
                metrics.get('retweet_count', 0) * 3 +  # Retweets are highly engaging
                metrics.get('like_count', 0) * 2 +      # Likes show approval
                metrics.get('reply_count', 0) * 4 +     # Replies show discussion
                metrics.get('quote_count', 0) * 2       # Quotes spread content
            )

        # Sort by engagement score (descending), then by timestamp (most recent first)
        sorted_ticks = sorted(
            ticks,
            key=lambda t: (calculate_engagement(t), t.timestamp),
            reverse=True
        )

        # Return IDs of top 1-2 posts
        return [tick.id for tick in sorted_ticks[:2]]

    def create_topic_digest(self, topic: str, bars_data: List[Dict[str, Any]], lookback_hours: int = 1) -> TopicDigest:
        """
        Create a digest over multiple bars for a topic.
        Uses reasoning model for higher-quality analysis.
        """
        if not bars_data:
            return TopicDigest(
                topic=topic,
                generated_at=datetime.now(timezone.utc),
                time_range=f"Last {lookback_hours} hour(s)",
                overall_summary="No recent activity to summarize",
                key_developments=[],
                trending_elements=[],
                sentiment_trend="stable",
                recommendations=["Continue monitoring for activity"]
            )

        # Get current time for context
        now = datetime.now(timezone.utc)
        
        # Create a summary of the bars with cleaner time formatting
        # Format sentiment as a label for readability
        def sentiment_label(s):
            if s is None:
                return "unknown"
            if isinstance(s, (int, float)):
                if s < 0.3:
                    return f"negative ({s:.2f})"
                elif s > 0.7:
                    return f"positive ({s:.2f})"
                else:
                    return f"neutral ({s:.2f})"
            return str(s)
        
        bars_summary = "\n".join([
            f"Bar {i+1} ({bar.get('start', 'unknown')}): {bar.get('summary', 'No summary')} "
            f"({bar.get('post_count', 0)} posts, sentiment: {sentiment_label(bar.get('sentiment'))})"
            for i, bar in enumerate(bars_data[-12:])  # Last 12 bars
        ])
        
        total_posts = sum(b.get("post_count", 0) for b in bars_data)

        user_prompt = f"""Topic: {topic}
Current time: {now.strftime('%Y-%m-%d %H:%M')} UTC
Time Period: Last {lookback_hours} hour(s)
Total posts across all bars: {total_posts}
Bar Summaries ({len(bars_data)} total bars, most recent last):

{bars_summary}"""

        payload = self._structured_call(
            model=self.reasoning_model,
            system_prompt="""You are creating an executive digest for a topic's recent activity across multiple time windows.
Provide contextual analysis of trends, developments, and recommendations for monitoring.""",
            user_prompt=user_prompt,
            schema=TopicDigest,
        )

        if isinstance(payload, TopicDigest):
            return payload

        raise RuntimeError(f"Grok API call failed for create_topic_digest({topic}). No fallback available.")

    # -------------------------------------------------------------------------
    # Async versions (run blocking calls in thread pool)
    # -------------------------------------------------------------------------

    async def summarize_bar_async(
        self, 
        topic: str, 
        ticks: List[Tick], 
        start_time: datetime, 
        end_time: datetime
    ) -> BarSummary:
        """
        Async version of summarize_bar.
        Runs the blocking xai-sdk call in a thread pool to avoid blocking the event loop.
        """
        return await asyncio.to_thread(
            self.summarize_bar,
            topic=topic,
            ticks=ticks,
            start_time=start_time,
            end_time=end_time
        )

    async def create_topic_digest_async(
        self, 
        topic: str, 
        bars_data: List[Dict[str, Any]], 
        lookback_hours: int = 1
    ) -> TopicDigest:
        """
        Async version of create_topic_digest.
        Runs the blocking xai-sdk call in a thread pool to avoid blocking the event loop.
        """
        return await asyncio.to_thread(
            self.create_topic_digest,
            topic=topic,
            bars_data=bars_data,
            lookback_hours=lookback_hours
        )


__all__ = [
    "GrokAdapter",
    "IntelSummary",
    "FactCheckReport",
    "DigestOverview",
    "BarSummary",
    "TopicDigest"
]

