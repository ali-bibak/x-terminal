"""
SQLite database module for X Terminal backend.
Provides simple connection management and query helpers.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).parent.parent / "db.sqlite3"


def init_db():
    """Initialize the database with schema."""
    schema_path = Path(__file__).parent / "schema.sql"
    with sqlite3.connect(DB_PATH) as conn:
        with open(schema_path) as f:
            conn.executescript(f.read())
        conn.commit()


@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Enable dict-like access
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class Database:
    """Simple database interface for X Terminal."""

    # Topics
    @staticmethod
    def create_topic(topic_id: str, query: str) -> None:
        """Create a new topic to watch."""
        with get_db() as db:
            db.execute(
                "INSERT INTO topics (id, query) VALUES (?, ?)", (topic_id, query)
            )

    @staticmethod
    def get_active_topics() -> List[Dict[str, Any]]:
        """Get all active topics."""
        with get_db() as db:
            cursor = db.execute(
                "SELECT * FROM topics WHERE is_active = TRUE ORDER BY created_at DESC"
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def update_topic_poll_time(topic_id: str) -> None:
        """Update last polled timestamp for a topic."""
        with get_db() as db:
            db.execute(
                "UPDATE topics SET last_polled_at = CURRENT_TIMESTAMP WHERE id = ?",
                (topic_id,),
            )

    # Bars
    @staticmethod
    def create_bar(
        topic_id: str,
        start_time: str,
        end_time: str,
        post_count: int,
        summary: str,
        sentiment_score: Optional[float] = None,
    ) -> int:
        """Create a new bar (time-bucketed aggregate)."""
        with get_db() as db:
            cursor = db.execute(
                """INSERT INTO bars (topic_id, start_time, end_time, post_count, summary, sentiment_score)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(topic_id, start_time) DO UPDATE SET
                   end_time = excluded.end_time,
                   post_count = excluded.post_count,
                   summary = excluded.summary,
                   sentiment_score = excluded.sentiment_score""",
                (topic_id, start_time, end_time, post_count, summary, sentiment_score),
            )
            return cursor.lastrowid

    @staticmethod
    def get_recent_bars(topic_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent bars for a topic."""
        with get_db() as db:
            cursor = db.execute(
                """SELECT * FROM bars
                   WHERE topic_id = ?
                   ORDER BY start_time DESC
                   LIMIT ?""",
                (topic_id, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    # Ticks
    @staticmethod
    def create_tick(
        tick_id: str,
        topic_id: str,
        bar_id: Optional[int],
        author_id: str,
        author_username: str,
        text: str,
        created_at: str,
        like_count: int = 0,
        retweet_count: int = 0,
        reply_count: int = 0,
    ) -> None:
        """Create a new tick (individual post)."""
        with get_db() as db:
            db.execute(
                """INSERT OR IGNORE INTO ticks
                   (id, topic_id, bar_id, author_id, author_username, text,
                    created_at, like_count, retweet_count, reply_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    tick_id,
                    topic_id,
                    bar_id,
                    author_id,
                    author_username,
                    text,
                    created_at,
                    like_count,
                    retweet_count,
                    reply_count,
                ),
            )

    @staticmethod
    def get_ticks_for_bar(bar_id: int) -> List[Dict[str, Any]]:
        """Get all ticks associated with a bar."""
        with get_db() as db:
            cursor = db.execute(
                "SELECT * FROM ticks WHERE bar_id = ? ORDER BY created_at DESC",
                (bar_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    # Digests
    @staticmethod
    def create_digest(
        topic_id: str,
        start_time: str,
        end_time: str,
        summary: str,
        key_trends: Optional[str] = None,
        recommendations: Optional[str] = None,
    ) -> int:
        """Create a topic digest."""
        with get_db() as db:
            cursor = db.execute(
                """INSERT INTO digests (topic_id, start_time, end_time, summary, key_trends, recommendations)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (topic_id, start_time, end_time, summary, key_trends, recommendations),
            )
            return cursor.lastrowid

    @staticmethod
    def get_latest_digest(topic_id: str) -> Optional[Dict[str, Any]]:
        """Get the most recent digest for a topic."""
        with get_db() as db:
            cursor = db.execute(
                "SELECT * FROM digests WHERE topic_id = ? ORDER BY created_at DESC LIMIT 1",
                (topic_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


# Initialize database on import
init_db()
