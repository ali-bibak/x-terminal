#!/usr/bin/env python3
"""
CLI for testing XAdapter functionality.

Usage:
    python -m adapter.x.cli

Commands:
    search  - Search recent posts by query
    bar     - Fetch posts for a specific time window (like a bar)
    counts  - Get tweet counts over time (requires elevated access)
"""

import cmd
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

# Ensure backend is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from adapter.x import (
    XAdapter,
    XAdapterError,
    XAuthenticationError,
    XRateLimitError,
    XAPIError,
    Tick
)


load_dotenv()


def _print_verbose_error(e: XAdapterError):
    """Print verbose error information."""
    print("\n" + "=" * 60)
    print("✗ ERROR DETAILS")
    print("=" * 60)
    print(f"  Type: {type(e).__name__}")
    print(f"  Message: {e}")
    
    if isinstance(e, XAuthenticationError):
        print("\n  💡 Troubleshooting:")
        print("     - Check X_BEARER_TOKEN environment variable is set")
        print("     - Verify the token is valid and not expired")
        print("     - Ensure you have API access enabled in X Developer Portal")
    
    elif isinstance(e, XRateLimitError):
        if e.reset_time:
            reset_dt = datetime.fromtimestamp(e.reset_time, tz=timezone.utc)
            now = datetime.now(timezone.utc)
            wait_seconds = max(0, (reset_dt - now).total_seconds())
            print(f"  Reset Time: {reset_dt.strftime('%H:%M:%S UTC')} (in {int(wait_seconds)}s)")
        if e.limit:
            print(f"  Limit: {e.limit} requests per window")
        if e.remaining is not None:
            print(f"  Remaining: {e.remaining}")
        
        print("\n  💡 Troubleshooting:")
        if e.reset_time:
            reset_dt = datetime.fromtimestamp(e.reset_time, tz=timezone.utc)
            now = datetime.now(timezone.utc)
            wait_seconds = max(0, (reset_dt - now).total_seconds())
            print(f"     - Wait {int(wait_seconds)} seconds before retrying")
        else:
            print("     - Wait a few minutes before retrying")
        print("     - Check your X API tier limits:")
        print("       • Free:  1,500 tweets/month (50/day average)")
        print("       • Basic: 10,000 tweets/month ($100/mo)")
        print("       • Pro:   1,000,000 tweets/month ($5,000/mo)")
        print("     - Use 'ratelimit' command to check current status")
    
    elif isinstance(e, XAPIError):
        if e.status_code:
            print(f"  Status Code: {e.status_code}")
        if e.response_text:
            # Try to parse as JSON for nicer formatting
            try:
                error_json = json.loads(e.response_text)
                print(f"  Response:")
                for key, value in error_json.items():
                    if isinstance(value, list):
                        print(f"    {key}:")
                        for item in value:
                            if isinstance(item, dict):
                                for k, v in item.items():
                                    print(f"      {k}: {v}")
                            else:
                                print(f"      - {item}")
                    else:
                        print(f"    {key}: {value}")
            except (json.JSONDecodeError, TypeError):
                print(f"  Response: {e.response_text[:500]}")
        
        print("\n  💡 Troubleshooting:")
        if e.status_code == 400:
            print("     - Check query syntax (special chars may need escaping)")
            print("     - Verify time range is valid (not in future, not too old)")
        elif e.status_code == 403:
            print("     - Your API access level may not support this endpoint")
            print("     - Check if the endpoint requires elevated access")
        elif e.status_code == 404:
            print("     - The requested resource was not found")
        elif e.status_code and e.status_code >= 500:
            print("     - X API is experiencing issues, try again later")
    
    print("=" * 60 + "\n")


class XAdapterCLI(cmd.Cmd):
    """Interactive CLI for testing XAdapter."""
    
    intro = """
╔═══════════════════════════════════════════════════════════════╗
║                     X Adapter CLI                              ║
║  Commands: search, bar, ratelimit, status, help, quit          ║
╚═══════════════════════════════════════════════════════════════╝
"""
    prompt = "x> "

    def __init__(self):
        super().__init__()
        try:
            self.adapter = XAdapter()
            if self.adapter.is_configured:
                print("✓ XAdapter initialized with bearer token")
            else:
                print("⚠ XAdapter initialized WITHOUT bearer token - API calls will fail")
        except Exception as e:
            print(f"✗ Failed to initialize XAdapter: {e}")
            self.adapter = None

    def _print_tick(self, tick: Tick, index: int = None):
        """Pretty print a tick."""
        prefix = f"[{index}] " if index is not None else ""
        timestamp = tick.timestamp.strftime("%H:%M:%S")
        
        # Truncate text for display
        text = tick.text.replace("\n", " ")[:100]
        if len(tick.text) > 100:
            text += "..."
        
        likes = tick.metrics.get("like_count", 0)
        retweets = tick.metrics.get("retweet_count", 0)
        
        print(f"{prefix}[{timestamp}] @{tick.author}")
        print(f"   {text}")
        print(f"   ♥ {likes}  🔁 {retweets}  ID: {tick.id}")
        print()

    def do_status(self, arg):
        """Show adapter status and configuration."""
        if not self.adapter:
            print("✗ Adapter not initialized")
            return
        
        print("\n=== X Adapter Status ===")
        print(f"Configured: {'Yes' if self.adapter.is_configured else 'No'}")
        print(f"Base URL: {self.adapter.BASE_URL}")
        
        # Show rate limit status from last API call
        self.do_ratelimit(arg)

    def do_ratelimit(self, arg):
        """
        Show current rate limit status from X API.
        
        Usage: ratelimit
        
        Shows remaining requests and when the limit resets.
        Note: Values are from the last API response.
        """
        if not self.adapter:
            print("✗ Adapter not initialized")
            return
        
        status = self.adapter.get_rate_limit_status()
        
        print("\n=== X API Rate Limit Status ===")
        
        if status["limit"] is None:
            print("  ⚠ No rate limit data yet - make an API call first")
            print("\n  Note: X API tiers have different limits:")
            print("    • Free:  1,500 tweets/month (very limited!)")
            print("    • Basic: 10,000 tweets/month ($100/mo)")
            print("    • Pro:   1,000,000 tweets/month ($5,000/mo)")
        else:
            remaining = status["remaining"]
            limit = status["limit"]
            pct_used = ((limit - remaining) / limit * 100) if limit else 0
            
            # Visual bar
            bar_len = 30
            filled = int((limit - remaining) / limit * bar_len) if limit else 0
            bar = "█" * filled + "░" * (bar_len - filled)
            
            print(f"  Remaining: {remaining}/{limit}")
            print(f"  Used: [{bar}] {pct_used:.1f}%")
            
            if status["reset_time_str"]:
                print(f"  Resets at: {status['reset_time_str']} (in {status['seconds_until_reset']}s)")
            
            if status["last_updated"]:
                print(f"  Last updated: {status['last_updated'].strftime('%H:%M:%S')}")
            
            # Warnings
            if remaining == 0:
                print("\n  ⛔ RATE LIMITED - wait for reset before making more requests")
            elif remaining <= 5:
                print(f"\n  ⚠️ WARNING: Only {remaining} requests remaining!")
            elif remaining <= 20:
                print(f"\n  ℹ️ Low: {remaining} requests remaining")
        
        print()

    def do_search(self, arg):
        """
        Search recent posts.
        
        Usage: search <query> [minutes] [max_results]
        
        Examples:
            search $TSLA
            search bitcoin 15 50
            search "LA earthquake" 30 100
        """
        if not self.adapter:
            print("✗ Adapter not initialized")
            return
        
        if not arg:
            print("Usage: search <query> [minutes] [max_results]")
            print("Example: search $TSLA 10 50")
            return
        
        parts = arg.split()
        query = parts[0]
        minutes = int(parts[1]) if len(parts) > 1 else 10
        max_results = int(parts[2]) if len(parts) > 2 else 50
        
        # Use query as topic
        topic = query.strip('"')
        
        print(f"\nSearching for '{query}' (last {minutes} min, max {max_results})...")
        print("-" * 60)
        
        try:
            ticks = self.adapter.search_recent(
                query=query,
                topic=topic,
                minutes=minutes,
                max_results=max_results
            )
            
            if not ticks:
                print("No posts found.")
                return
            
            print(f"Found {len(ticks)} posts:\n")
            for i, tick in enumerate(ticks, 1):
                self._print_tick(tick, i)
            
            # Summary
            total_likes = sum(t.metrics.get("like_count", 0) for t in ticks)
            total_retweets = sum(t.metrics.get("retweet_count", 0) for t in ticks)
            print("-" * 60)
            print(f"Total: {len(ticks)} posts, {total_likes} likes, {total_retweets} retweets")
            
        except XAdapterError as e:
            _print_verbose_error(e)

    def do_bar(self, arg):
        """
        Fetch posts for a specific time window (simulating bar fetch).
        
        Usage: bar <query> <minutes_ago> <window_minutes>
        
        Examples:
            bar $TSLA 10 5    # Posts from 10-5 minutes ago (5min window)
            bar bitcoin 30 15  # Posts from 30-15 minutes ago (15min window)
        """
        if not self.adapter:
            print("✗ Adapter not initialized")
            return
        
        if not arg:
            print("Usage: bar <query> <minutes_ago> <window_minutes>")
            print("Example: bar $TSLA 10 5")
            return
        
        parts = arg.split()
        if len(parts) < 3:
            print("Usage: bar <query> <minutes_ago> <window_minutes>")
            return
        
        query = parts[0]
        minutes_ago = int(parts[1])
        window_minutes = int(parts[2])
        
        now = datetime.now(timezone.utc)
        end_time = now - timedelta(minutes=minutes_ago)
        start_time = end_time - timedelta(minutes=window_minutes)
        
        topic = query.strip('"')
        
        print(f"\nFetching bar: {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}")
        print(f"Query: '{query}'")
        print("-" * 60)
        
        try:
            ticks = self.adapter.search_for_bar(
                query=query,
                topic=topic,
                start_time=start_time,
                end_time=end_time
            )
            
            if not ticks:
                print("No posts in this window.")
                return
            
            print(f"Found {len(ticks)} posts:\n")
            for i, tick in enumerate(ticks, 1):
                self._print_tick(tick, i)
            
            # Bar summary
            total_likes = sum(t.metrics.get("like_count", 0) for t in ticks)
            total_retweets = sum(t.metrics.get("retweet_count", 0) for t in ticks)
            print("-" * 60)
            print(f"Bar Summary:")
            print(f"  Window: {start_time.strftime('%Y-%m-%d %H:%M')} - {end_time.strftime('%H:%M')}")
            print(f"  Posts: {len(ticks)}")
            print(f"  Total Likes: {total_likes}")
            print(f"  Total Retweets: {total_retweets}")
            
            # Show tick IDs for debugging
            print(f"  Tick IDs: {[t.id for t in ticks[:5]]}{'...' if len(ticks) > 5 else ''}")
            
        except XAdapterError as e:
            _print_verbose_error(e)

    def do_counts(self, arg):
        """
        Get tweet counts over time.
        
        Note: Requires Academic Research or Enterprise API access.
        
        Usage: counts <query> [granularity] [minutes]
        
        Examples:
            counts $TSLA minute 60
            counts bitcoin hour 1440
        """
        if not self.adapter:
            print("✗ Adapter not initialized")
            return
        
        if not arg:
            print("Usage: counts <query> [granularity] [minutes]")
            print("Example: counts $TSLA minute 60")
            return
        
        parts = arg.split()
        query = parts[0]
        granularity = parts[1] if len(parts) > 1 else "minute"
        minutes = int(parts[2]) if len(parts) > 2 else 60
        
        print(f"\nGetting counts for '{query}' (last {minutes} min, by {granularity})...")
        print("-" * 60)
        
        try:
            counts = self.adapter.get_tweet_counts(
                query=query,
                granularity=granularity,
                minutes=minutes
            )
            
            if not counts:
                print("No count data returned (may require elevated API access).")
                return
            
            print(f"{'Time':<20} {'Count':>10}")
            print("-" * 32)
            for entry in counts:
                start = entry.get("start", "")[:16]
                count = entry.get("tweet_count", 0)
                bar = "█" * min(count, 50)
                print(f"{start:<20} {count:>10}  {bar}")
            
            total = sum(e.get("tweet_count", 0) for e in counts)
            print("-" * 32)
            print(f"{'Total':<20} {total:>10}")
            
        except XAdapterError as e:
            _print_verbose_error(e)

    def do_json(self, arg):
        """
        Search and output results as JSON.
        
        Usage: json <query> [minutes] [max_results]
        """
        if not self.adapter:
            print("✗ Adapter not initialized")
            return
        
        if not arg:
            print("Usage: json <query> [minutes] [max_results]")
            return
        
        parts = arg.split()
        query = parts[0]
        minutes = int(parts[1]) if len(parts) > 1 else 10
        max_results = int(parts[2]) if len(parts) > 2 else 50
        
        topic = query.strip('"')
        
        try:
            ticks = self.adapter.search_recent(
                query=query,
                topic=topic,
                minutes=minutes,
                max_results=max_results
            )
            
            output = [tick.model_dump(mode="json") for tick in ticks]
            print(json.dumps(output, indent=2, default=str))
            
        except XAdapterError as e:
            _print_verbose_error(e)

    def do_quit(self, arg):
        """Exit the CLI."""
        print("Goodbye!")
        return True

    def do_exit(self, arg):
        """Exit the CLI."""
        return self.do_quit(arg)

    def do_EOF(self, arg):
        """Handle Ctrl+D."""
        print()
        return self.do_quit(arg)

    def emptyline(self):
        """Do nothing on empty line."""
        pass


def main():
    """Run the CLI."""
    cli = XAdapterCLI()
    try:
        cli.cmdloop()
    except KeyboardInterrupt:
        print("\nGoodbye!")


if __name__ == "__main__":
    main()

