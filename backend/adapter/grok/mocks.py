"""
Mock implementations for GrokAdapter fallback data.
These are separated from the main adapter to avoid using fake data in production.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import List, Dict, Any

from . import IntelSummary, FactCheckReport, DigestOverview, BarSummary, TopicDigest
from ..models import Tick


def mock_rng(seed_source: str) -> random.Random:
    """Create a deterministic random number generator for consistent mock data."""
    seed = abs(hash(seed_source)) % (2**32)
    return random.Random(seed)


def mock_intel_summary(handle: str, posts: List[str]) -> IntelSummary:
    """Mock implementation of IntelSummary for testing."""
    rng = mock_rng(handle)
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


def mock_fact_check_report(url: str, text: str) -> FactCheckReport:
    """Mock implementation of FactCheckReport for testing."""
    rng = mock_rng(url + text)
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


def mock_digest_overview(highlights: List[str]) -> DigestOverview:
    """Mock implementation of DigestOverview for testing."""
    base = highlights or ["Quiet cycle so far — consider running a watch on a priority handle."]
    recommended = [
        "Escalate the spiking topic to comms.",
        "Add a fact-check flag to the contested link.",
        "Schedule a digest push to the leadership chat.",
    ]
    return DigestOverview(
        generated_at=datetime.now(timezone.utc),
        highlights=base[:4],
        risk_outlook="Moderate risk. Sentiment is noisy but nothing is on fire.",
        recommended_actions=recommended,
    )


def mock_bar_summary(topic: str, ticks: List[Tick], start_time: datetime, end_time: datetime) -> BarSummary:
    """Mock implementation of BarSummary for testing."""
    rng = mock_rng(f"{topic}_{start_time}_{end_time}")
    post_count = len(ticks)

    if post_count == 0:
        return BarSummary(
            summary="No posts in this time window",
            key_themes=[],
            sentiment="neutral",
            post_count=0,
            engagement_level="low"
        )

    # Select highlight posts (simple mock: just pick first 1-2)
    highlight_posts = [tick.id for tick in ticks[:2]] if ticks else None

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
        engagement_level=engagement,
        highlight_posts=highlight_posts
    )


def mock_topic_digest(topic: str, bars_data: List[Dict[str, Any]], lookback_hours: int) -> TopicDigest:
    """Mock implementation of TopicDigest for testing."""
    rng = mock_rng(f"{topic}_digest_{lookback_hours}")

    total_posts = sum(bar.get('post_count', 0) for bar in bars_data)
    active_bars = len([b for b in bars_data if b.get('post_count', 0) > 0])

    time_range = f"Last {lookback_hours} hour(s)"

    if total_posts == 0:
        return TopicDigest(
            topic=topic,
            generated_at=datetime.now(timezone.utc),
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
        generated_at=datetime.now(timezone.utc),
        time_range=time_range,
        overall_summary=overall_summary,
        key_developments=developments,
        trending_elements=trending,
        sentiment_trend=sentiment_trend,
        recommendations=recommendations
    )
