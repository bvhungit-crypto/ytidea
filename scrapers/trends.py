"""
scrapers/trends.py — Google Trends breakout detection
Tìm topics đang tăng đột biến trong 24-48h
"""
import logging
import time
from pytrends.request import TrendReq
from core.models import RawSignal

logger = logging.getLogger(__name__)

# Keywords mặc định theo niche
NICHE_KEYWORDS = {
    "revenge_drama": [
        "revenge story", "karma story", "betrayal story",
        "cheating karma", "justice served",
    ],
    "space_futurism": [
        "space discovery", "nasa news", "alien life",
        "space travel", "future technology",
    ],
    "finance_business": [
        "stock market crash", "crypto news", "passive income",
        "side hustle", "financial freedom",
    ],
    "tech_ai": [
        "AI news", "ChatGPT", "new technology",
        "robot news", "artificial intelligence",
    ],
    "lifestyle_vlog": [
        "self improvement", "morning routine", "productivity tips",
        "relationship advice", "life hacks",
    ],
    "general": [
        "trending news", "viral story", "shocking news",
    ],
}


def scrape_google_trends(
    niche: str,
    timeframe: str = "now 1-d",  # 1 ngày gần nhất
    geo: str = "US",
    min_growth: int = 50,  # % tăng tối thiểu
) -> list[RawSignal]:
    """
    Lấy trending topics từ Google Trends.
    timeframe options: 'now 1-d', 'now 7-d', 'today 1-m'
    """
    keywords = NICHE_KEYWORDS.get(niche, NICHE_KEYWORDS["general"])
    signals  = []

    try:
        pytrends = TrendReq(
            hl="en-US",
            tz=360,
            timeout=(10, 25),
        )

        # Lấy related queries cho từng keyword
        for keyword in keywords[:3]:  # Giới hạn 3 keyword để tránh rate limit
            try:
                pytrends.build_payload(
                    [keyword],
                    cat=0,
                    timeframe=timeframe,
                    geo=geo,
                )

                # Related queries — tìm queries đang tăng
                related = pytrends.related_queries()
                rising  = related.get(keyword, {}).get("rising")

                if rising is not None and not rising.empty:
                    for _, row in rising.head(5).iterrows():
                        query      = str(row.get("query", "")).strip()
                        value      = int(row.get("value", 0))

                        if not query or value < min_growth:
                            continue

                        # Breakout = tăng > 5000% (Google dùng "Breakout" thay số)
                        is_breakout = value >= 5000

                        signals.append(RawSignal(
                            title=        query,
                            source=       "google_trends",
                            view_count=   value,
                            channel_name= "Google Trends",
                            metadata={
                                "keyword":      keyword,
                                "growth":       value,
                                "is_breakout":  is_breakout,
                                "geo":          geo,
                                "timeframe":    timeframe,
                            },
                        ))

                        if is_breakout:
                            logger.info(f"🔥 BREAKOUT: '{query}' (+{value}%)")

                time.sleep(1)  # Tránh rate limit

            except Exception as e:
                logger.warning(f"Trends error for '{keyword}': {e}")
                continue

        # Lấy trending searches hôm nay
        try:
            trending_df = pytrends.trending_searches(pn="united_states")
            for _, row in trending_df.head(10).iterrows():
                query = str(row[0]).strip()
                if query:
                    signals.append(RawSignal(
                        title=        query,
                        source=       "google_trends_daily",
                        view_count=   0,
                        channel_name= "Google Trends Daily",
                        metadata={
                            "geo":      geo,
                            "type":     "daily_trending",
                        },
                    ))
        except Exception as e:
            logger.warning(f"Daily trending error: {e}")

    except Exception as e:
        logger.error(f"Google Trends scraper error: {e}")

    logger.info(f"Google Trends ({niche}): {len(signals)} signals")
    return signals