"""
Typed helper wrapping Grok (xai-sdk) flows for the X Terminal backend.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import find_dotenv, load_dotenv
from pydantic import BaseModel, Field

from ..models import Tick
from ..rate_limiter import RateLimiter, shared_limiter

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


class MonitorInsight(BaseModel):
    topic: str = Field(description="Topic being monitored")
    headline: str = Field(description="One-line headline for the latest pulse")
    impact_score: int = Field(description="0-100 subjective impact score", ge=0, le=100)
    tags: List[str] = Field(description="Tags that categorize the event")


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

    summary: str = Field(
        description="Brief summary of what happened in this time window"
    )
    key_themes: List[str] = Field(description="Main topics or themes discussed")
    sentiment: float = Field(
        description="Sentiment score from 0.0 (very negative) to 1.0 (very positive), with 0.5 being neutral"
    )
    post_count: int = Field(description="Number of posts in this bar")
    engagement_level: str = Field(description="low/medium/high engagement level")
    highlight_posts: Optional[List[str]] = Field(
        default=None, description="IDs of 1-2 highlight posts"
    )


class TopicDigest(BaseModel):
    """Digest over multiple bars for a topic."""

    topic: str = Field(description="Topic name")
    generated_at: datetime = Field(description="When this digest was generated")
    time_range: str = Field(description="Time period covered by this digest")
    overall_summary: str = Field(
        description="High-level summary of the topic's activity"
    )
    key_developments: List[str] = Field(description="Major developments or changes")
    trending_elements: List[str] = Field(description="What's gaining traction")
    sentiment_trend: str = Field(description="How sentiment has evolved")
    recommendations: List[str] = Field(
        description="Suggested actions or monitoring points"
    )


class GrokAdapter:
    """
    Adapter for Grok API calls with proper error handling, logging, and rate limiting.
    """

    def __init__(self, rate_limiter: Optional[RateLimiter] = None) -> None:
        self.api_key = os.getenv("XAI_API_KEY")
        self.fast_model = os.getenv(
            "GROK_MODEL_FAST", "grok-4-1-fast"
        )  # Updated to current fast model
        self.reasoning_model = os.getenv(
            "GROK_MODEL_REASONING", "grok-4-1-fast-reasoning"
        )  # Updated to current model
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
            logger.warning(
                "GrokAdapter initialized without API client (using fallbacks)"
            )
            self._client = None

    @property
    def is_live(self) -> bool:
        return self._client is not None

    def _structured_call(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
    ) -> Optional[BaseModel]:
        """
        Perform a structured chat call via xai-sdk if available.
        Includes rate limiting and proper error handling.
        """
        if not self._client:
            logger.debug("No client available, returning None")
            return None

        try:
            # Apply rate limiting with appropriate category
            category = (
                "grok_reasoning" if model == self.reasoning_model else "grok_fast"
            )
            self.rate_limiter.wait_if_needed(category)

            logger.debug(
                f"Making API call to model {model} with rate limit category {category}"
            )

            # Try the current API pattern first
            try:
                chat = self._client.chat.create(model=model)
                chat.append(system(system_prompt))
                chat.append(user(user_prompt))
                _, payload = chat.parse(schema)  # type: ignore[arg-type]
                logger.debug("API call successful")
                return payload
            except AttributeError:
                # Fallback for potential API changes in newer versions
                logger.debug("Trying alternative API pattern")
                # If the API has changed, we might need different method calls
                # For now, fall back to the error case
                raise

        except Exception as e:
            logger.error(f"API call failed: {e}", exc_info=True)
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
        raise RuntimeError(
            f"Grok API call failed for summarize_user({handle}). No fallback available."
        )

    def monitor_topic(self, topic: str) -> MonitorInsight:
        payload = self._structured_call(
            model=self.fast_model,
            system_prompt="Provide a short monitor insight for a live-ops dashboard.",
            user_prompt=f"Topic: {topic}\nNeed headline + impact score + tags.",
            schema=MonitorInsight,
        )
        if isinstance(payload, MonitorInsight):
            return payload
        raise RuntimeError(
            f"Grok API call failed for monitor_topic({topic}). No fallback available."
        )

    def fact_check(self, url: str, text: str) -> FactCheckReport:
        payload = self._structured_call(
            model=self.reasoning_model,
            system_prompt="Fact check the provided X post. Respond with a structured verdict.",
            user_prompt=f"URL: {url}\nText:\n{text}",
            schema=FactCheckReport,
        )
        if isinstance(payload, FactCheckReport):
            return payload
        raise RuntimeError(
            f"Grok API call failed for fact_check({url}). No fallback available."
        )

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

    def summarize_bar(
        self, topic: str, ticks: List[Tick], start_time: datetime, end_time: datetime
    ) -> BarSummary:
        """
        Generate a summary for a time-barred window of posts.
        Uses fast model for quick, structured summaries.

        Args:
            topic: Topic name
            ticks: List of Tick objects
            start_time: Start of the time window
            end_time: End of the time window

        Returns:
            BarSummary with sentiment as float (0.0-1.0) and highlight_posts
        """
        if not ticks:
            return BarSummary(
                summary="No posts in this time window",
                key_themes=[],
                sentiment=0.5,  # Neutral
                post_count=0,
                engagement_level="low",
                highlight_posts=[],
            )

        # Select highlight posts (top 1-2 by engagement)
        highlight_posts = self._select_highlight_posts(ticks)

        # Create a readable representation of the posts
        posts_text = "\n".join(
            [
                f"@{tick.author}: {tick.text[:200]}..."
                for tick in ticks[:10]  # Limit to first 10 posts for summary
            ]
        )

        time_range = f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"

        user_prompt = f"""Topic: {topic}
Time Window: {time_range}
Posts ({len(ticks)} total):

{posts_text}

{"... and " + str(len(ticks) - 10) + " more posts" if len(ticks) > 10 else ""}

Highlight post IDs: {highlight_posts}"""

        payload = self._structured_call(
            model=self.fast_model,
            system_prompt="""You are a critical analyst summarizing social media posts for a professional trading/monitoring dashboard.

SPAM FILTERING (CRITICAL - apply first):
Identify and EXCLUDE these from your summary:
- Giveaway scams ("Send X get Y back", "Free BTC/ETH")
- Trading signal promotions ("Join my group", "100x gains")
- Bot-like repetitive content
- Wallet address begging
- Obvious pump-and-dump shills
- "DM me" or follow-bait posts

Your summary should focus ONLY on legitimate content. Only include posts that are not spam or scams. If there are no posts that are not spam or scams, say nothing, and return an empty output.

If there are spam, do not mention it at all. Again, say nothing if no legitimate posts exist.

SENTIMENT SCORING (based on NON-SPAM content only):
- 0.0-0.2: Very negative (panic, crashes, scams exposed, major bad news)
- 0.2-0.4: Negative (concerns, doubt, bearish sentiment, criticism)
- 0.4-0.6: Neutral (mixed signals, factual updates, no clear direction)
- 0.6-0.8: Positive (optimism, good news, bullish but measured)
- 0.8-1.0: Very positive (euphoria, major wins, breakthrough news)

ANALYSIS RULES:
1. Base sentiment ONLY on legitimate posts, not spam
2. "Moon" talk without substance = skeptical (0.5-0.6 max)
3. Distinguish genuine news from hype
4. If >50% spam, add "High spam ratio" to key_themes
5. Default to neutral (0.5) when content is mostly noise

KEY_THEMES should reflect actual topics discussed (excluding spam). If spam dominates, include "High spam ratio" as a theme.

HIGHLIGHT_POSTS should be from legitimate content only, not spam.""",
            user_prompt=user_prompt,
            schema=BarSummary,
        )

        if isinstance(payload, BarSummary):
            # Ensure post_count matches actual data
            payload.post_count = len(ticks)
            # Set highlight posts
            payload.highlight_posts = highlight_posts
            return payload

        raise RuntimeError(
            f"Grok API call failed for summarize_bar({topic}). No fallback available."
        )

    def _select_highlight_posts(self, ticks: List[Tick]) -> List[str]:
        """
        Select 1-2 highlight posts based on engagement and recency.

        Returns:
            List of post IDs (1-2 highlights)
        """
        if not ticks:
            return []

        def calculate_engagement(tick: Tick) -> int:
            metrics = tick.metrics or {}
            return (
                metrics.get("like_count", 0) * 3
                + metrics.get("retweet_count", 0) * 5
                + metrics.get("reply_count", 0) * 2
                + metrics.get("quote_count", 0) * 4
            )

        # Sort by engagement (desc), then by recency (desc)
        sorted_ticks = sorted(
            ticks, key=lambda t: (calculate_engagement(t), t.timestamp), reverse=True
        )

        # Return IDs of top 1-2 posts
        return [tick.id for tick in sorted_ticks[:2]]

    def create_topic_digest(
        self, topic: str, bars_data: List[Dict[str, Any]], lookback_hours: int = 1
    ) -> TopicDigest:
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
                recommendations=["Continue monitoring for activity"],
            )

        # Create a summary of the bars
        bars_summary = "\n".join(
            [
                f"Bar {i + 1} ({bar.get('start', 'unknown')}): {bar.get('summary', 'No summary')} "
                f"({bar.get('post_count', 0)} posts)"
                for i, bar in enumerate(
                    bars_data[-12:]
                )  # Last 12 bars (assuming 5min bars = 1 hour)
            ]
        )

        user_prompt = f"""Topic: {topic}
Time Period: Last {lookback_hours} hour(s)
Bar Summaries ({len(bars_data)} total bars):

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

        raise RuntimeError(
            f"Grok API call failed for create_topic_digest({topic}). No fallback available."
        )

    # -------------------------------------------------------------------------
    # Async versions (run blocking calls in thread pool)
    # -------------------------------------------------------------------------

    async def summarize_bar_async(
        self, topic: str, ticks: List[Tick], start_time: datetime, end_time: datetime
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
            end_time=end_time,
        )

    async def create_topic_digest_async(
        self, topic: str, bars_data: List[Dict[str, Any]], lookback_hours: int = 1
    ) -> TopicDigest:
        """
        Async version of create_topic_digest.
        Runs the blocking xai-sdk call in a thread pool to avoid blocking the event loop.
        """
        return await asyncio.to_thread(
            self.create_topic_digest,
            topic=topic,
            bars_data=bars_data,
            lookback_hours=lookback_hours,
        )


__all__ = [
    "GrokAdapter",
    "IntelSummary",
    "MonitorInsight",
    "FactCheckReport",
    "DigestOverview",
    "BarSummary",
    "TopicDigest",
]
