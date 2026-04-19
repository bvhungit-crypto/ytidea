"""
scrapers/youtube.py — Tầng 1: Thu thập signals từ YouTube Data API v3
"""
import os
import logging
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from core.models import ChannelConfig, RawSignal

logger = logging.getLogger(__name__)


def _build_yt():
    return build("youtube", "v3", developerKey=os.environ["YOUTUBE_API_KEY"])


def scrape_trending_vn(max_results: int = 50) -> tuple[list[RawSignal], int]:
    yt = _build_yt()
    signals = []
    quota_used = 0

    try:
        resp = yt.videos().list(
            part="snippet,statistics",
            chart="mostPopular",
            regionCode="US",
            maxResults=max_results,
            videoCategoryId="0",
        ).execute()
        quota_used += 1

        for item in resp.get("items", []):
            snippet = item.get("snippet", {})
            stats   = item.get("statistics", {})
            signals.append(RawSignal(
                title=       snippet.get("title", ""),
                source=      "youtube_trending",
                view_count=  int(stats.get("viewCount", 0)),
                channel_name=snippet.get("channelTitle", ""),
                tags=        snippet.get("tags", [])[:10],
                metadata={
                    "video_id":     item["id"],
                    "published_at": snippet.get("publishedAt"),
                    "description":  snippet.get("description", "")[:200],
                },
            ))

        logger.info(f"Trending US: {len(signals)} videos")
    except HttpError as e:
        logger.error(f"YouTube trending error: {e}")

    return signals, quota_used


def scrape_competitor_uploads(
    competitor_ids: list[str],
    days_back: int = 7,
) -> tuple[list[RawSignal], int]:
    from datetime import datetime, timedelta, timezone
    yt = _build_yt()
    signals = []
    quota_used = 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()

    for channel_id in competitor_ids[:5]:
        try:
            ch_resp = yt.channels().list(
                part="contentDetails,snippet",
                id=channel_id,
            ).execute()
            quota_used += 1

            if not ch_resp.get("items"):
                continue

            channel_name = ch_resp["items"][0]["snippet"]["title"]
            uploads_id = (
                ch_resp["items"][0]
                .get("contentDetails", {})
                .get("relatedPlaylists", {})
                .get("uploads", "")
            )
            if not uploads_id:
                continue

            pl_resp = yt.playlistItems().list(
                part="snippet",
                playlistId=uploads_id,
                maxResults=20,
            ).execute()
            quota_used += 1

            for item in pl_resp.get("items", []):
                snippet = item.get("snippet", {})
                published = snippet.get("publishedAt", "")
                if published < cutoff:
                    continue

                signals.append(RawSignal(
                    title=       snippet.get("title", ""),
                    source=      "competitor",
                    view_count=  0,
                    channel_name=channel_name,
                    metadata={
                        "video_id":     snippet.get("resourceId", {}).get("videoId"),
                        "published_at": published,
                        "competitor_channel_id": channel_id,
                    },
                ))

        except HttpError as e:
            logger.warning(f"Competitor {channel_id} error: {e}")
            continue

    logger.info(f"Competitor uploads: {len(signals)} videos")
    return signals, quota_used


def scrape_search_suggestions(
    seed_keywords: list[str],
    max_per_keyword: int = 10,
) -> tuple[list[RawSignal], int]:
    yt = _build_yt()
    signals = []
    quota_used = 0
    seen_titles = set()

    for keyword in seed_keywords[:5]:
        try:
            resp = yt.search().list(
                part="snippet",
                q=keyword,
                type="video",
                maxResults=max_per_keyword,
                regionCode="US",
                order="viewCount",
            ).execute()
            quota_used += 100

            for item in resp.get("items", []):
                snippet = item.get("snippet", {})
                title = snippet.get("title", "")
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    signals.append(RawSignal(
                        title=       title,
                        source=      "search_suggest",
                        channel_name=snippet.get("channelTitle", ""),
                        metadata={
                            "video_id":  item["id"].get("videoId"),
                            "keyword":   keyword,
                        },
                    ))

        except HttpError as e:
            logger.warning(f"Search suggest '{keyword}' error: {e}")
            continue

    logger.info(f"Search suggestions: {len(signals)} videos")
    return signals, quota_used


def run_all_scrapers(config: ChannelConfig) -> tuple[list[RawSignal], int]:
    all_signals = []
    total_quota = 0

    if config.competitor_ids:
        s2, q2 = scrape_competitor_uploads(config.competitor_ids)
        all_signals.extend(s2)
        total_quota += q2

    s3, q3 = scrape_search_suggestions(config.seed_keywords[:5])
    all_signals.extend(s3)
    total_quota += q3

    # Reddit scraper
    from scrapers.reddit import scrape_reddit_rss
    reddit_signals = scrape_reddit_rss(config.niche, max_per_subreddit=10)
    all_signals.extend(reddit_signals)

    # Google Trends
    #from scrapers.trends import scrape_google_trends
    # trends_signals = scrape_google_trends(config.niche, geo="US")
    # all_signals.extend(trends_signals)

    all_signals = [s for s in all_signals if s.title.strip()]

    logger.info(
        f"[{config.name}] Total signals: {len(all_signals)} "
        f"| YouTube quota used: {total_quota}"
    )
    return all_signals, total_quota