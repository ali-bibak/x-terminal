import requests
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
import os
from dotenv import load_dotenv

load_dotenv()
    
class XAdaptor:
    BASE_URL = "https://api.x.com/2/tweets/search/recent"

    def __init__(self, bearer_token: str):
        bearer_token = bearer_token or os.environ.get("X_BEARER_TOKEN")
        if not bearer_token:
            raise ValueError("Bearer token must be provided")
        self.bearer_token = bearer_token
        self.headers = {
            "Authorization": f"Bearer {self.bearer_token}",
        }
    
    def _get_time_bounds(self, minutes: int):
        now = datetime.now(timezone.utc)
        safe_end = now - timedelta(seconds=20)

        end_time = safe_end.isoformat(timespec="seconds").replace("+00:00", "Z")
        start_time = (safe_end - timedelta(minutes=minutes)).isoformat(timespec="seconds").replace("+00:00", "Z")

        return start_time, end_time

    def search_topic(self, topic: str, minutes: int = 10, max_results: int = 100):
        """
        Search for tweets containing `topic` in the last `minutes` minutes.
        """
        if max_results < 10 or max_results > 100:
            raise ValueError("max_results must be between 10 and 100")

        start_time, end_time = self._get_time_bounds(minutes)

        params = {
            "query": f"{topic} -is:retweet",
            "start_time": start_time,
            "end_time": end_time,
            "max_results": max_results,
            "tweet.fields": "text,created_at,author_id,public_metrics,lang",
            "expansions": "author_id",
            "user.fields": "username,name,verified"
        }

        try:
            response = requests.get(self.BASE_URL, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if "data" not in data or not data["data"]:
                print(f"No tweets found for '{topic}' in the last {minutes} minutes.")
                return []

            tweets = data["data"]
            users = {user["id"]: user for user in data.get("includes", {}).get("users", [])}

            result = []
            for tweet in tweets:
                author_id = tweet.get("author_id")
                username = users.get(author_id, {}).get("username", "unknown")

                result.append({
                    "id": tweet["id"],
                    "text": tweet.get("text", "[NO TEXT]"),
                    "author_id": author_id,
                    "username": username,
                    "created_at": tweet.get("created_at"),
                    "likes": tweet.get("public_metrics", {}).get("like_count", 0),
                    "retweets": tweet.get("public_metrics", {}).get("retweet_count", 0),
                })

            return result

        except requests.exceptions.HTTPError as e:
            print(f"HTTP Error {e.response.status_code}: {e.response.text}")
            return []
        except requests.exceptions.RequestException as e:
            print(f"Network/request error: {e}")
            return []
        except Exception as e:
            print(f"Unexpected error: {e}")
            return []
        
all = ["XAdaptor"]

