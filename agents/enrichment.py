"""
agents/enrichment.py — Tầng 3: Enrichment dùng Claude Sonnet
"""
import json
import asyncio
import logging
import os
import anthropic
from pydantic import ValidationError
from core.models import ChannelConfig, RawSignal, IdeaCard, TitleOption
from core.config import log_cost
from supabase import Client

logger = logging.getLogger(__name__)
SONNET_MODEL = "claude-haiku-4-5-20251001"


def build_localization_system(config: ChannelConfig) -> str:
    top_videos_text = ""
    if config.top_videos:
        top_videos_text = "\n".join(
            f"- {v.get('title', '')} ({v.get('views', 0):,} views)"
            for v in config.top_videos[:3]
        )
    return f"""You are a YouTube content strategist for the "{config.name}" channel.

CHANNEL DNA:
- Niche: {config.niche}
- Language: {config.language}
- Target audience: {config.target_audience}
- Story type: {config.story_type}
- Emotional trigger: {config.emotional_trigger}
- Twist type: {config.twist_type}
- Audience insights: {config.audience_insights}
- Avoid: {', '.join(config.avoid_topics)}

TOP PERFORMING VIDEOS:
{top_videos_text}

TASK: Analyze the video signal and adapt it to fit this channel's DNA.
Output language: {config.language}

Return JSON ONLY:
{{
  "localized_context": "2-3 sentences on how to adapt this signal for this channel",
  "suggested_tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "source_url": ""
}}"""


def build_hook_writer_system(config: ChannelConfig) -> str:
    # Lấy learned insights nếu có
    learned_insights = config.niche_config.get("learned_insights", "")
    learned_section = f"\n\nLEARNED FROM REAL PERFORMANCE DATA:\n{learned_insights}" if learned_insights else ""

    return f"""You are an expert YouTube hook and title writer for the "{config.name}" channel.

CHANNEL DNA:
- Niche: {config.niche}
- Language: {config.language}
- Tone: {config.tone}
- Hook style: {config.hook_style}
- Target audience: {config.target_audience}
- Emotional trigger: {config.emotional_trigger}
- Twist type: {config.twist_type}
- Avoid: {', '.join(config.avoid_topics)}{learned_section}

TASK: Create a complete YouTube idea card in {config.language}.

Return JSON ONLY:
{{
  "title_options": [
    {{"label": "A", "title": "Title option A (list/number format)", "hook": "15-second hook for A"}},
    {{"label": "B", "title": "Title option B (question/mystery format)", "hook": "15-second hook for B"}},
    {{"label": "C", "title": "Title option C (story/emotion format)", "hook": "15-second hook for C"}}
  ],
  "best_title": "Copy exact best title",
  "hook": "Hook for best title",
  "outline": [
    "Intro: hook + preview (30 seconds)",
    "Part 1: [specific content]",
    "Part 2: [specific content]",
    "Part 3: [specific content]",
    "Outro: recap + CTA"
  ],
  "script_brief": "3-5 sentences: story setup, turning point, climax, tone, key scene to dramatize"
}}

Title rules:
- 8 to 12 words minimum, DO NOT write short titles
- Must include specific details: who, what happened, outcome
- Examples of GOOD titles: "She Was Fired On Her Wedding Day — Then Karma Hit Back Hard"
- Examples of BAD titles: "Revenge Story", "Revenge Served", "Revenge Found"
- Start with emotional keyword
- Output in {config.language}"""


async def localization_agent(
    signal: RawSignal,
    config: ChannelConfig,
    client: anthropic.AsyncAnthropic,
    supabase: Client,
) -> dict:
    source_url = ""
    if signal.metadata.get("video_id"):
        source_url = f"https://www.youtube.com/watch?v={signal.metadata['video_id']}"

    user_msg = f"""Original title: {signal.title}
Source: {signal.source}
Source URL: {source_url}

Adapt this for the channel. Return JSON only."""

    try:
        resp = await client.messages.create(
            model=SONNET_MODEL,
            max_tokens=400,
            system=build_localization_system(config),
            messages=[{"role": "user", "content": user_msg}],
        )
        log_cost(supabase, config.channel_id, "enrichment", SONNET_MODEL,
                 resp.usage.input_tokens, resp.usage.output_tokens)

        raw = resp.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        result["source_url"] = source_url
        return result
    except Exception as e:
        logger.error(f"Localization agent error for '{signal.title[:40]}': {e}")
        return {
            "localized_context": signal.title,
            "suggested_tags":    signal.tags[:5],
            "source_url":        source_url,
        }


async def hook_writer_agent(
    signal: RawSignal,
    localized: dict,
    config: ChannelConfig,
    client: anthropic.AsyncAnthropic,
    supabase: Client,
) -> IdeaCard | None:
    user_msg = f"""Original title: {signal.title}
Adapted concept: {localized.get('localized_context', signal.title)}
Suggested tags: {', '.join(localized.get('suggested_tags', []))}

Create the idea card. Return JSON only."""

    try:
        resp = await client.messages.create(
            model=SONNET_MODEL,
            max_tokens=2000,
            system=build_hook_writer_system(config),
            messages=[{"role": "user", "content": user_msg}],
        )
        log_cost(supabase, config.channel_id, "enrichment", SONNET_MODEL,
                 resp.usage.input_tokens, resp.usage.output_tokens)

        raw = resp.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        data = json.loads(raw)
        return IdeaCard(
            raw_signal=        signal.title,
            source=            signal.source,
            localized_context= localized.get("localized_context", signal.title),
            title_options=     [TitleOption(**t) for t in data["title_options"]],
            best_title=        data["best_title"],
            hook=              data["hook"],
            outline=           data["outline"],
            tags=              localized.get("suggested_tags", [])[:8],
            script_brief=      data.get("script_brief", ""),
        )
    except (json.JSONDecodeError, ValidationError, KeyError) as e:
        logger.error(f"Hook writer error for '{signal.title[:40]}': {e}")
        return None


async def enrich_signal(
    signal: RawSignal,
    config: ChannelConfig,
    client: anthropic.AsyncAnthropic,
    supabase: Client,
) -> tuple[IdeaCard | None, str]:
    localized = await localization_agent(signal, config, client, supabase)
    idea_card = await hook_writer_agent(signal, localized, config, client, supabase)
    source_url = localized.get("source_url", "")
    return idea_card, source_url


async def run_enrichment_pipeline(
    signals: list[RawSignal],
    config: ChannelConfig,
    supabase: Client,
    concurrency: int = 5,
) -> list[tuple[IdeaCard, str]]:
    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    semaphore = asyncio.Semaphore(concurrency)

    async def bounded_enrich(signal: RawSignal) -> tuple[IdeaCard | None, str]:
        async with semaphore:
            return await enrich_signal(signal, config, client, supabase)

    tasks = [bounded_enrich(sig) for sig in signals]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    idea_cards = []
    for r in results:
        if isinstance(r, tuple) and isinstance(r[0], IdeaCard):
            idea_cards.append(r)
        elif isinstance(r, Exception):
            logger.error(f"Enrichment task exception: {r}")

    logger.info(
        f"[{config.name}] Enrichment done: "
        f"{len(signals)} signals → {len(idea_cards)} idea cards"
    )
    return idea_cards
