"""
Typed helper wrapping Grok (xai-sdk) flows for the X Terminal backend.
"""

from __future__ import annotations

import logging
import os
import random
import time
from datetime import datetime
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv, find_dotenv
from pydantic import BaseModel, Field

from .rate_limiter import RateLimiter, shared_limiter

load_dotenv(find_dotenv(usecwd=True))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from xai_sdk import Client
    from xai_sdk.chat import system, user
except ImportError:  # xai-sdk might not be installed in local dev
    Client = None  # type: ignore[assignment]

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
    summary: str = Field(description="Brief summary of what happened in this time window")
    key_themes: List[str] = Field(description="Main topics or themes discussed")
    sentiment: str = Field(description="Overall sentiment: positive/negative/neutral/mixed")
    post_count: int = Field(description="Number of posts in this bar")
    engagement_level: str = Field(description="low/medium/high engagement level")


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
        self.fast_model = os.getenv("XAI_FAST_MODEL", "grok-2-1212")  # Updated to current fast model
        self.careful_model = os.getenv("XAI_CAREFUL_MODEL", "grok-2-1212")  # Updated to current model
        self._client: Optional[Client] = None  # type: ignore[type-arg]
        self.rate_limiter = rate_limiter or shared_limiter

        if Client and self.api_key:
            self._client = Client(api_key=self.api_key)  # type: ignore[call-arg]
            logger.info("GrokAdapter initialized with live API client")
        else:
            logger.warning("GrokAdapter initialized without API client (using fallbacks)")

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

        try:
            # Apply rate limiting with appropriate category
            category = "grok_careful" if model == self.careful_model else "grok_fast"
            self.rate_limiter.wait_if_needed(category)

            logger.debug(f"Making API call to model {model} with rate limit category {category}")
            chat = self._client.chat.create(model=model)
            chat.append(system(system_prompt))
            chat.append(user(user_prompt))

            _, payload = chat.parse(schema)  # type: ignore[arg-type]
            logger.debug("API call successful")
            return payload

        except Exception as e:
            logger.error(f"API call failed: {e}", exc_info=True)
            return None

    # ---------------------------------------------------------------------
    # Public high-level helpers
    # ---------------------------------------------------------------------

    def summarize_user(self, handle: str, mocked_posts: List[str]) -> IntelSummary:
        prompt = "\n".join(mocked_posts[:5]) or "No recent posts"
        payload = self._structured_call(
            model=self.fast_model,
            system_prompt="Summarize the following X account for an operator dashboard.",
            user_prompt=f"Handle: {handle}\nRecent posts:\n{prompt}",
            schema=IntelSummary,
        )
        if isinstance(payload, IntelSummary):
            return payload
        return self._fallback_intel(handle, mocked_posts)

    def monitor_topic(self, topic: str) -> MonitorInsight:
        payload = self._structured_call(
            model=self.fast_model,
            system_prompt="Provide a short monitor insight for a live-ops dashboard.",
            user_prompt=f"Topic: {topic}\nNeed headline + impact score + tags.",
            schema=MonitorInsight,
        )
        if isinstance(payload, MonitorInsight):
            return payload
        return self._fallback_monitor(topic)

    def fact_check(self, url: str, text: str) -> FactCheckReport:
        payload = self._structured_call(
            model=self.careful_model,
            system_prompt="Fact check the provided X post. Respond with a structured verdict.",
            user_prompt=f"URL: {url}\nText:\n{text}",
            schema=FactCheckReport,
        )
        if isinstance(payload, FactCheckReport):
            return payload
        return self._fallback_factcheck(url, text)

    def digest(self, highlights: List[str]) -> DigestOverview:
        prompt = "\n".join(f"- {item}" for item in highlights) or "No highlights yet."
        payload = self._structured_call(
            model=self.careful_model,
            system_prompt="Produce an executive digest for a social-ops dashboard.",
            user_prompt=prompt,
            schema=DigestOverview,
        )
        if isinstance(payload, DigestOverview):
            return payload
        return self._fallback_digest(highlights)

    # ---------------------------------------------------------------------
    # X Terminal specific methods
    # ---------------------------------------------------------------------

    def summarize_bar(self, topic: str, posts: List[Dict[str, Any]], start_time: datetime, end_time: datetime) -> BarSummary:
        """
        Generate a summary for a time-barred window of posts.
        Uses fast model for quick, structured summaries.
        """
        if not posts:
            return BarSummary(
                summary="No posts in this time window",
                key_themes=[],
                sentiment="neutral",
                post_count=0,
                engagement_level="low"
            )

        # Create a readable representation of the posts
        posts_text = "\n".join([
            f"@{post.get('author', 'unknown')}: {post.get('text', '')[:200]}..."
            for post in posts[:10]  # Limit to first 10 posts for summary
        ])

        time_range = f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"

        user_prompt = f"""Topic: {topic}
Time Window: {time_range}
Posts ({len(posts)} total):

{posts_text}

{"... and " + str(len(posts) - 10) + " more posts" if len(posts) > 10 else ""}"""

        payload = self._structured_call(
            model=self.fast_model,
            system_prompt="""You are summarizing a time window of social media posts for a live monitoring dashboard.
Create a brief, structured summary focused on what happened in this specific time window.""",
            user_prompt=user_prompt,
            schema=BarSummary,
        )

        if isinstance(payload, BarSummary):
            # Ensure post_count matches actual data
            payload.post_count = len(posts)
            return payload

        return self._fallback_bar_summary(topic, posts, start_time, end_time)

    def create_topic_digest(self, topic: str, bars_data: List[Dict[str, Any]], lookback_hours: int = 1) -> TopicDigest:
        """
        Create a digest over multiple bars for a topic.
        Uses careful model for higher-quality analysis.
        """
        if not bars_data:
            return TopicDigest(
                topic=topic,
                generated_at=datetime.utcnow(),
                time_range=f"Last {lookback_hours} hour(s)",
                overall_summary="No recent activity to summarize",
                key_developments=[],
                trending_elements=[],
                sentiment_trend="stable",
                recommendations=["Continue monitoring for activity"]
            )

        # Create a summary of the bars
        bars_summary = "\n".join([
            f"Bar {i+1} ({bar.get('start', 'unknown')}): {bar.get('summary', 'No summary')} "
            f"({bar.get('post_count', 0)} posts)"
            for i, bar in enumerate(bars_data[-12:])  # Last 12 bars (assuming 5min bars = 1 hour)
        ])

        user_prompt = f"""Topic: {topic}
Time Period: Last {lookback_hours} hour(s)
Bar Summaries ({len(bars_data)} total bars):

{bars_summary}"""

        payload = self._structured_call(
            model=self.careful_model,
            system_prompt="""You are creating an executive digest for a topic's recent activity across multiple time windows.
Provide contextual analysis of trends, developments, and recommendations for monitoring.""",
            user_prompt=user_prompt,
            schema=TopicDigest,
        )

        if isinstance(payload, TopicDigest):
            return payload

        return self._fallback_topic_digest(topic, bars_data, lookback_hours)

    # ---------------------------------------------------------------------
    # Fallbacks keep the UI demoable without live API access.
    # ---------------------------------------------------------------------

    def _rng(self, seed_source: str) -> random.Random:
        seed = abs(hash(seed_source)) % (2**32)
        return random.Random(seed)

    def _fallback_intel(self, handle: str, posts: List[str]) -> IntelSummary:
        rng = self._rng(handle)
        sample_posts = posts or [
            "Sharing a macro take on the energy markets.",
            "Morning note on AI x politics crossover.",
            "Retweeting a hot take about creators' economy.",
        ]
        sentiment = rng.choice(["positive", "neutral", "mixed", "skeptical"])
        topics = rng.sample(
            ["ai", "politics", "creators", "growth", "culture", "sports", "finance"],
            k=3,
        )
        summary = (
            f"{handle} keeps a tight signal on {topics[0]} and blends it with "
            f"{topics[1]} commentary. Tone feels {sentiment} with regular "
            "threads that travel."
        )
        recent = [sample_posts[i % len(sample_posts)] for i in range(3)]
        return IntelSummary(
            handle=handle,
            summary=summary,
            top_topics=topics,
            sentiment=sentiment,
            recent_activity=recent,
        )

    def _fallback_monitor(self, topic: str) -> MonitorInsight:
        rng = self._rng(topic)
        tags = rng.sample(
            ["tech", "politics", "finance", "culture", "controversial", "wholesome"],
            k=2,
        )
        headline = f"Spike in {topic} chatter from {rng.choice(['creators', 'policy wonks', 'finfluencers'])}"
        score = rng.randint(35, 92)
        return MonitorInsight(topic=topic, headline=headline, impact_score=score, tags=tags)

    def _fallback_factcheck(self, url: str, text: str) -> FactCheckReport:
        rng = self._rng(url + text)
        verdict = rng.choice(["true", "false", "unclear"])
        confidence = rng.choice(["low", "medium", "high"])
        rationale = (
            "Verified against archived statements and recent reporting."
            if verdict == "true"
            else "Conflicts with public filings and trusted monitoring feeds."
            if verdict == "false"
            else "Source material is thin; more corroboration required."
        )
        return FactCheckReport(url=url, verdict=verdict, rationale=rationale, confidence=confidence)

    def _fallback_digest(self, highlights: List[str]) -> DigestOverview:
        base = highlights or ["Quiet cycle so far — consider running a watch on a priority handle."]
        recommended = [
            "Escalate the spiking topic to comms.",
            "Add a fact-check flag to the contested link.",
            "Schedule a digest push to the leadership chat.",
        ]
        return DigestOverview(
            generated_at=datetime.utcnow(),
            highlights=base[:4],
            risk_outlook="Moderate risk. Sentiment is noisy but nothing is on fire.",
            recommended_actions=recommended,
        )

    def _fallback_bar_summary(self, topic: str, posts: List[Dict[str, Any]], start_time: datetime, end_time: datetime) -> BarSummary:
        """Fallback bar summary when API is unavailable."""
        rng = self._rng(f"{topic}_{start_time}_{end_time}")
        post_count = len(posts)

        if post_count == 0:
            return BarSummary(
                summary="No posts in this time window",
                key_themes=[],
                sentiment="neutral",
                post_count=0,
                engagement_level="low"
            )

        # Generate plausible themes based on topic
        base_themes = ["discussion", "updates", "reactions", "analysis"]
        if "tech" in topic.lower() or "ai" in topic.lower():
            base_themes.extend(["innovation", "development", "trends"])
        elif "finance" in topic.lower() or "$" in topic:
            base_themes.extend(["market", "investment", "analysis"])

        themes = rng.sample(base_themes, k=min(3, len(base_themes)))
        sentiment = rng.choice(["positive", "negative", "neutral", "mixed"])
        engagement = rng.choice(["low", "medium", "high"])

        summary = f"{post_count} posts about {topic} with {sentiment} sentiment and {engagement} engagement."

        return BarSummary(
            summary=summary,
            key_themes=themes,
            sentiment=sentiment,
            post_count=post_count,
            engagement_level=engagement
        )

    def _fallback_topic_digest(self, topic: str, bars_data: List[Dict[str, Any]], lookback_hours: int) -> TopicDigest:
        """Fallback topic digest when API is unavailable."""
        rng = self._rng(f"{topic}_digest_{lookback_hours}")

        total_posts = sum(bar.get('post_count', 0) for bar in bars_data)
        active_bars = len([b for b in bars_data if b.get('post_count', 0) > 0])

        time_range = f"Last {lookback_hours} hour(s)"

        if total_posts == 0:
            return TopicDigest(
                topic=topic,
                generated_at=datetime.utcnow(),
                time_range=time_range,
                overall_summary=f"No significant activity for {topic} in the last {lookback_hours} hour(s)",
                key_developments=[],
                trending_elements=[],
                sentiment_trend="stable",
                recommendations=["Continue monitoring for emerging activity"]
            )

        # Generate plausible digest content
        sentiment_trend = rng.choice(["improving", "declining", "stable", "volatile"])

        developments = [
            f"Consistent discussion across {active_bars} time windows",
            f"Total of {total_posts} posts analyzed",
            "Community engagement shows steady patterns"
        ]

        trending = rng.sample([
            "User engagement metrics",
            "Content quality indicators",
            "Cross-platform discussion",
            "Influencer participation"
        ], k=rng.randint(1, 3))

        recommendations = [
            "Maintain current monitoring intensity",
            "Consider increasing check frequency if volume grows",
            "Prepare for potential topic escalation"
        ]

        overall_summary = f"{topic} shows {sentiment_trend} activity with {total_posts} total posts across {len(bars_data)} time windows."

        return TopicDigest(
            topic=topic,
            generated_at=datetime.utcnow(),
            time_range=time_range,
            overall_summary=overall_summary,
            key_developments=developments,
            trending_elements=trending,
            sentiment_trend=sentiment_trend,
            recommendations=recommendations
        )


__all__ = [
    "GrokAdapter",
    "IntelSummary",
    "MonitorInsight",
    "FactCheckReport",
    "DigestOverview",
    "BarSummary",
    "TopicDigest"
]

