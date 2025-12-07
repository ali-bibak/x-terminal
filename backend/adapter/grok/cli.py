from __future__ import annotations

import json
from typing import List

from . import GrokAdapter
from ..x import Tick

PROMPT = """\
Commands:
  intel      → summarize a handle
  factcheck  → run a fact-check on a URL + text
  digest     → build a digest from highlight bullets
  barsum     → summarize a bar of posts (X Terminal)
  topicdig   → create topic digest from bars (X Terminal)
  help       → show this message
  quit       → exit
"""


def _split_list(value: str) -> List[str]:
    return [item.strip() for item in value.split("|") if item.strip()]


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def main() -> None:
    adapter = GrokAdapter()
    print("GrokAdapter CLI — type 'help' for options. Live:", adapter.is_live)

    while True:
        try:
            command = input("grok> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break

        if not command:
            continue

        if command in {"quit", "exit"}:
            break

        if command == "help":
            print(PROMPT)
            continue

        if command == "intel":
            handle = input("Handle (e.g. @operator): ").strip() or "@demo"
            posts_raw = input("Recent posts (separate with |, optional): ").strip()
            posts = _split_list(posts_raw) if posts_raw else []
            summary = adapter.summarize_user(handle, posts)
            _print(summary.model_dump())
            continue

        if command == "factcheck":
            url = input("URL: ").strip() or "https://x.com/demo/status/1"
            text = input("Post text (optional): ").strip() or "Sample post text about Grok."
            report = adapter.fact_check(url, text)
            _print(report.model_dump())
            continue

        if command == "digest":
            highlights_raw = input("Highlights (separate with |, optional): ").strip()
            highlights = _split_list(highlights_raw) if highlights_raw else []
            digest = adapter.digest(highlights)
            _print(digest.model_dump())
            continue

        if command == "barsum":
            topic = input('Topic (e.g. "$TSLA"): ').strip() or "$TSLA"
            posts_raw = input("Posts (format: author|text|author|text...): ").strip()
            ticks = []
            if posts_raw:
                parts = posts_raw.split("|")
                for i in range(0, len(parts), 2):
                    if i + 1 < len(parts):
                        author = parts[i].strip()
                        text = parts[i+1].strip()
                        tick = Tick(
                            id=f"cli_{i//2}",
                            author=author,
                            text=text,
                            timestamp=datetime.now(timezone.utc),
                            permalink=f"https://twitter.com/{author}/status/cli_{i//2}",
                            metrics={"retweet_count": 0, "like_count": 0, "reply_count": 0, "quote_count": 0},
                            topic=topic
                        )
                        ticks.append(tick)

            from datetime import datetime, timedelta, timezone
            start_time = datetime.now(timezone.utc) - timedelta(minutes=5)
            end_time = datetime.now(timezone.utc)

            summary = adapter.summarize_bar(topic, ticks, start_time, end_time)
            _print(summary.model_dump())
            continue

        if command == "topicdig":
            topic = input('Topic (e.g. "$TSLA"): ').strip() or "$TSLA"
            bars_raw = input("Bars data (JSON-like, optional): ").strip()
            bars_data = []
            if bars_raw:
                # Simple parsing for demo - in real usage this would be proper JSON
                try:
                    import json
                    bars_data = json.loads(bars_raw)
                except:
                    # Fallback to mock data
                    bars_data = [
                        {"start": "10:00", "summary": "Initial discussion", "post_count": 5},
                        {"start": "10:05", "summary": "Growing momentum", "post_count": 12},
                        {"start": "10:10", "summary": "Peak activity", "post_count": 25}
                    ]

            digest = adapter.create_topic_digest(topic, bars_data, lookback_hours=1)
            _print(digest.model_dump())
            continue

        print("Unknown command. Type 'help' to see options.")


if __name__ == "__main__":
    main()

