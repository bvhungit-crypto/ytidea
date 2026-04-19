"""
core/filter.py — Tầng 2: Filter dùng Claude Haiku (rẻ) + Groq fallback
"""
import json
import logging
import os
from difflib import SequenceMatcher
import anthropic
from core.models import ChannelConfig, RawSignal
from supabase import Client

logger = logging.getLogger(__name__)
HAIKU_MODEL = "claude-haiku-4-5-20251001"


def dedup_by_title(
    signals: list[RawSignal],
    existing_titles: list[str],
    threshold: float = 0.72,
) -> list[RawSignal]:
    def similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    filtered = []
    for sig in signals:
        too_similar = any(
            similarity(sig.title, existing) >= threshold
            for existing in existing_titles
        )
        if not too_similar:
            filtered.append(sig)

    deduped = []
    for sig in filtered:
        too_similar = any(
            similarity(sig.title, kept.title) >= threshold
            for kept in deduped
        )
        if not too_similar:
            deduped.append(sig)

    removed = len(signals) - len(deduped)
    logger.info(f"Title dedup: {len(signals)} → {len(deduped)} (-{removed})")
    return deduped


def load_existing_titles(
    supabase: Client,
    channel_id: str,
    days_back: int = 90,
) -> list[str]:
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()
    resp = (
        supabase.table("ideas")
        .select("best_title, raw_signal")
        .eq("channel_id", channel_id)
        .gte("created_at", cutoff)
        .execute()
    )
    titles = []
    for row in resp.data:
        if row.get("best_title"):
            titles.append(row["best_title"])
        if row.get("raw_signal"):
            titles.append(row["raw_signal"])
    logger.info(f"Loaded {len(titles)} existing titles for dedup")
    return titles


def haiku_filter(
    signals: list[RawSignal],
    config: ChannelConfig,
    supabase: Client,
    batch_size: int = 20,
) -> list[RawSignal]:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    kept_signals = []
    filter_prompt = config.niche_config.get("filter_prompt", "")

    system_msg = f"""You are a content filter for the "{config.name}" YouTube channel.
Niche: {config.niche}
Filter rule: {filter_prompt if filter_prompt else f'Keep content related to {config.niche}. Remove unrelated content.'}
Avoid: {', '.join(config.avoid_topics)}

Evaluate each title and return a JSON array in exact order:
[{{"keep": true/false, "reason": "one sentence"}}]
ONLY return JSON, no extra text."""

    for i in range(0, len(signals), batch_size):
        batch = signals[i: i + batch_size]
        titles_list = "\n".join(
            f"{j+1}. [{s.source}] {s.title}"
            for j, s in enumerate(batch)
        )
        user_msg = f"Titles to evaluate:\n{titles_list}\n\nReturn JSON array of {len(batch)} items."

        try:
            resp = client.messages.create(
                model=HAIKU_MODEL,
                max_tokens=800,
                system=system_msg,
                messages=[{"role": "user", "content": user_msg}],
            )
            from core.config import log_cost
            log_cost(supabase, config.channel_id, "filter", HAIKU_MODEL,
                     resp.usage.input_tokens, resp.usage.output_tokens)

            raw_text = resp.content[0].text.strip()
            if "```" in raw_text:
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]
            results = json.loads(raw_text)
            for signal, result in zip(batch, results):
                if result.get("keep", False):
                    kept_signals.append(signal)
        except Exception as e:
            logger.error(f"Haiku filter batch {i//batch_size} error: {e}")
            kept_signals.extend(batch)

    logger.info(f"Haiku filter: {len(signals)} → {len(kept_signals)}")
    return kept_signals


def check_ban_list(
    signals: list[RawSignal],
    topic_ban_list: list[str],
) -> list[RawSignal]:
    if not topic_ban_list:
        return signals
    ban_lower = [b.lower() for b in topic_ban_list]
    kept = []
    for sig in signals:
        title_lower = sig.title.lower()
        banned = any(ban in title_lower for ban in ban_lower)
        if not banned:
            kept.append(sig)
    logger.info(f"Ban list check: {len(signals)} → {len(kept)}")
    return kept


def run_filter_pipeline(
    signals: list[RawSignal],
    config: ChannelConfig,
    supabase: Client,
) -> list[RawSignal]:
    existing_titles = load_existing_titles(supabase, config.channel_id)
    signals = dedup_by_title(signals, existing_titles)
    signals = check_ban_list(signals, config.topic_ban_list)
    signals = haiku_filter(signals, config, supabase)
    logger.info(f"[{config.name}] Filter pipeline done: {len(signals)} clean signals")
    return signals