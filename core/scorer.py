"""
core/scorer.py — Tầng 4: Scoring engine 3 tiêu chí
"""
import math
import logging
from core.models import ChannelConfig, IdeaCard, ScoredIdea
from supabase import Client

logger = logging.getLogger(__name__)


def calc_trend_score(
    idea: IdeaCard,
    trending_view_counts: dict[str, int],
) -> float:
    best_match_views = 0

    for tag in idea.tags:
        tag_lower = tag.lower()
        for title, views in trending_view_counts.items():
            if tag_lower in title:
                best_match_views = max(best_match_views, views)

    if best_match_views <= 0:
        return 30.0

    score = min(100, math.log10(best_match_views + 1) / math.log10(10_000_000) * 100)
    return round(score, 1)


def calc_competition_score(
    idea: IdeaCard,
    supabase: Client,
    channel_id: str,
    competitor_titles: list[str],
) -> float:
    from difflib import SequenceMatcher

    def sim(a: str, b: str) -> float:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    overlap_count = sum(
        1 for ct in competitor_titles
        if any(sim(idea.best_title, ct) > 0.45 or tag.lower() in ct.lower()
               for tag in idea.tags[:3])
    )

    if overlap_count == 0:
        return 95.0
    elif overlap_count == 1:
        return 75.0
    elif overlap_count == 2:
        return 55.0
    elif overlap_count <= 4:
        return 35.0
    else:
        return 15.0


def calc_keyword_score(
    idea: IdeaCard,
    seed_keywords: list[str],
) -> float:
    keywords_lower = [k.lower() for k in seed_keywords]
    title_lower    = idea.best_title.lower()
    tags_lower     = [t.lower() for t in idea.tags]
    context_lower  = idea.localized_context.lower()

    hits = 0
    for kw in keywords_lower:
        kw_lower = kw.lower()
        if (kw_lower in title_lower or
            any(kw_lower in t for t in tags_lower) or
            kw_lower in context_lower):
            hits += 1

    if not keywords_lower:
        return 50.0

    ratio = hits / len(keywords_lower)
    score = 20 + ratio * 75
    return round(min(95, score), 1)


def calc_final_score(
    trend: float,
    competition: float,
    keyword: float,
    weights: dict,
) -> tuple[float, str]:
    w_trend = weights.get("trend", 0.40)
    w_comp  = weights.get("competition", 0.35)
    w_kw    = weights.get("keyword_match", 0.25)

    final = trend * w_trend + competition * w_comp + keyword * w_kw
    final = round(final, 1)

    if final >= 70:
        tier = "A"
    elif final >= 45:
        tier = "B"
    else:
        tier = "C"

    return final, tier


def score_ideas(
    idea_cards: list[tuple],
    config: ChannelConfig,
    supabase: Client,
    trending_signals: list,
    competitor_signals: list,
) -> list[tuple[ScoredIdea, str]]:
    trending_views = {
        s.title.lower(): s.view_count
        for s in trending_signals
        if s.source == "youtube_trending"
    }
    competitor_titles = [
        s.title.lower()
        for s in competitor_signals
        if s.source == "competitor"
    ]

    scored = []
    for idea, source_url in idea_cards:
        trend_s = calc_trend_score(idea, trending_views)
        comp_s  = calc_competition_score(
            idea, supabase, config.channel_id, competitor_titles
        )
        kw_s    = calc_keyword_score(idea, config.seed_keywords)

        final, tier = calc_final_score(
            trend_s, comp_s, kw_s, config.scoring_weights
        )

        scored.append((ScoredIdea(
            idea=              idea,
            trend_score=       trend_s,
            competition_score= comp_s,
            keyword_score=     kw_s,
            final_score=       final,
            tier=              tier,
        ), source_url))

    scored.sort(key=lambda x: x[0].final_score, reverse=True)

    tier_a = sum(1 for s, _ in scored if s.tier == "A")
    logger.info(
        f"[{config.name}] Scored {len(scored)} ideas | "
        f"Tier A: {tier_a} | Top score: {scored[0][0].final_score if scored else 0}"
    )
    return scored