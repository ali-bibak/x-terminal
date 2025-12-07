"""
Shared data models for adapters.
"""

from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel, Field


class Tick(BaseModel):
    """
    A single post (tweet) from X, representing a tick in our system.
    
    Attributes:
        id: Unique post ID
        author: Author handle (without @)
        text: Full post text
        timestamp: When the post was created
        metrics: Engagement metrics (like_count, retweet_count, etc.)
        topic: Topic this tick belongs to
    """
    id: str = Field(description="Unique post ID")
    author: str = Field(description="Author handle (without @)")
    text: str = Field(description="Full post text")
    timestamp: datetime = Field(description="When the post was created")
    metrics: Dict[str, int] = Field(default_factory=dict, description="Engagement metrics")
    topic: str = Field(description="Topic this tick belongs to")


__all__ = ["Tick"]

