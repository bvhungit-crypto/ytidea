"""
main.py — Pipeline chính
Usage:
  python main.py
  python main.py --dry-run
  python main.py --max-signals 5
"""
import os
import sys
import asyncio
import logging
import argparse
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            f"logs/run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)

from core.config import get_supabase, load_channel_configs
from core.models import RunStats
from scrapers.youtube import run_all_scrapers
from core.filter import run_filter_pipeline
from agents.enrichment import run_enrichment_pipeline
from core.scorer import score_ideas
from output.push import (
    save_ideas_to_supabase,
    push_to_google_sheet,
    send_telegram_digest,
    save_run_stats,
)


async def run_channel_pipeline(
    config,
    supabase,
    dry_run: bool = False,
    max_signals: int = 25,
) -> RunStats:
    stats = RunStats(channel_id=config.channel_id)
    start_time = time.time()

    logger.info(f"\n{'='*60}")
    logger.info(f"Starting pipeline: {config.name}")
    logger.info(f"{'='*60}")

    try:
        # Tầng 1
        logger.info("[ Layer 1 ] Scraping...")
        raw_signals, yt_quota = run_all_scrapers(config)
        stats.raw_count = len(raw_signals)
        logger.info(f"  → {len(raw_signals)} signals | Quota: {yt_quota}")

        if not raw_signals:
            stats.errors.append("No raw signals")
            return stats

        trending_signals   = [s for s in raw_signals if s.source == "youtube_trending"]
        competitor_signals = [s for s in raw_signals if s.source == "competitor"]

        # Tầng 2
        logger.info("[ Layer 2 ] Filtering...")
        clean_signals = run_filter_pipeline(raw_signals, config, supabase)
        stats.after_filter = len(clean_signals)
        stats.after_dedup  = len(clean_signals)
        logger.info(f"  → {len(clean_signals)} clean signals")

        if not clean_signals:
            stats.errors.append("All signals filtered")
            return stats

        if len(clean_signals) > max_signals:
            clean_signals = clean_signals[:max_signals]
            logger.info(f"  Capped to {max_signals} signals")

        # Tầng 3
        logger.info("[ Layer 3 ] Enrichment agents...")
        idea_cards = await run_enrichment_pipeline(clean_signals, config, supabase)
        stats.ideas_generated = len(idea_cards)
        logger.info(f"  → {len(idea_cards)} idea cards")

        if not idea_cards:
            stats.errors.append("No idea cards")
            return stats

        # Tầng 4
        logger.info("[ Layer 4 ] Scoring...")
        scored_ideas = score_ideas(
            idea_cards, config, supabase,
            trending_signals, competitor_signals,
        )
        stats.tier_a_count = sum(1 for s, _ in scored_ideas if s.tier == "A")

        logger.info("\nTop 7 ideas:")
        for i, (si, url) in enumerate(scored_ideas[:7], 1):
            logger.info(
                f"  {i}. [{si.tier}] {si.final_score:.1f} — {si.idea.best_title[:60]}"
            )

        if dry_run:
            logger.info("[DRY RUN] Skipping output")
            stats.runtime_seconds = time.time() - start_time
            return stats

        # Tầng 5
        logger.info("[ Layer 5 ] Saving...")
        save_ideas_to_supabase(scored_ideas, config, supabase, top_n=7)
        push_to_google_sheet(scored_ideas, config, top_n=7)

        # Tầng 6
        stats.runtime_seconds = time.time() - start_time
        logger.info("[ Layer 6 ] Sending Telegram...")
        await send_telegram_digest(scored_ideas, config, stats, top_n=7)

    except Exception as e:
        logger.exception(f"Pipeline error: {e}")
        stats.errors.append(str(e))
    finally:
        stats.runtime_seconds = time.time() - start_time

    return stats


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel-id", help="Run specific channel")
    parser.add_argument("--dry-run", action="store_true", help="Skip output")
    parser.add_argument("--max-signals", type=int, default=25, help="So signals toi da (default 25, test dung 5)")
    args = parser.parse_args()

    logger.info(f"\n{'#'*60}")
    logger.info(f"YouTube Idea Engine — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"{'#'*60}")

    supabase = get_supabase()
    configs  = load_channel_configs(supabase)

    if args.channel_id:
        configs = [c for c in configs if c.channel_id == args.channel_id]
        if not configs:
            logger.error(f"Channel {args.channel_id} not found")
            sys.exit(1)

    if not configs:
        logger.error("No active channels found")
        sys.exit(1)

    logger.info(f"Running for {len(configs)} channel(s)")

    all_stats = []
    for config in configs:
        stats = await run_channel_pipeline(
            config, supabase,
            dry_run=args.dry_run,
            max_signals=args.max_signals,
        )
        save_run_stats(stats, supabase)
        all_stats.append((config.name, stats))

    logger.info(f"\n{'='*60}")
    logger.info("SUMMARY")
    logger.info(f"{'='*60}")
    for name, stats in all_stats:
        status = "✓" if not stats.errors else "⚠"
        logger.info(
            f"{status} {name}: {stats.ideas_generated} ideas | "
            f"{stats.tier_a_count} Tier A | {stats.runtime_seconds:.0f}s"
            + (f" | ERRORS: {stats.errors}" if stats.errors else "")
        )


if __name__ == "__main__":
    asyncio.run(main())