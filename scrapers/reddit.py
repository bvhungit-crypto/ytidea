"""
scrapers/reddit.py — Scrape Reddit qua RSS (không cần API key)
"""
import logging
import feedparser
from core.models import RawSignal

logger = logging.getLogger(__name__)

SUBREDDITS = {
    "revenge_drama": [
        "pettyrevenge",
        "ProRevenge",
        "AmItheAsshole",
        "TrueOffMyChest",
        "relationship_advice",
        "survivinginfidelity",
        "NuclearRevenge",
        "MaliciousCompliance",
    ],
    "space_futurism": [
        "space",
        "Futurology",
        "scifi",
        "singularity",
        "artificial",
    ],
    "finance_business": [
        "personalfinance",
        "investing",
        "entrepreneur",
        "wallstreetbets",
    ],
    "tech_ai": [
        "artificial",
        "MachineLearning",
        "technology",
        "ChatGPT",
    ],
    "general": [
        "AskReddit",
        "tifu",
        "TrueOffMyChest",
    ],
}


def scrape_reddit_rss(
    niche: str,
    max_per_subreddit: int = 10,
) -> list[RawSignal]:
    subreddits = SUBREDDITS.get(niche, SUBREDDITS["general"])
    signals = []
    seen_titles = set()

    for subreddit in subreddits[:5]:
        try:
            url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={max_per_subreddit}"
            import urllib.request
            import json
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "yt-idea-engine/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read())

            posts = data.get("data", {}).get("children", [])
            for post in posts:
                post_data = post.get("data", {})
                title = post_data.get("title", "").strip()
                if not title or title in seen_titles:
                    continue
                if post_data.get("stickied"):
                    continue

                seen_titles.add(title)
                signals.append(RawSignal(
                    title=title,
                    source="reddit",
                    view_count=post_data.get("score", 0),
                    channel_name=f"r/{subreddit}",
                    metadata={
                        "subreddit": subreddit,
                        "url": f"https://reddit.com{post_data.get('permalink', '')}",
                        "num_comments": post_data.get("num_comments", 0),
                        "upvote_ratio": post_data.get("upvote_ratio", 0),
                    },
                ))

        except Exception as e:
            logger.warning(f"Reddit r/{subreddit} error: {e}")
            continue

    logger.info(f"Reddit scrape ({niche}): {len(signals)} posts")
    return signals