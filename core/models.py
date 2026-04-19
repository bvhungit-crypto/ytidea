"""
core/models.py — Pydantic schemas dùng xuyên suốt pipeline
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from pydantic import BaseModel, Field


# ─── Channel config (load từ Supabase) ───────────────────────────
@dataclass
class ChannelConfig:
    channel_id:         str
    name:               str
    youtube_channel_id: str
    seed_keywords:      list[str]
    competitor_ids:     list[str]
    tone:               str
    audience_profile:   dict
    scoring_weights:    dict
    topic_ban_list:     list[str]
    cooldown_days:      int
    # New fields
    language:           str = "en"
    niche:              str = "general"
    niche_config:       dict = field(default_factory=dict)
    target_audience:    str = ""
    hook_style:         str = ""
    top_videos:         list = field(default_factory=list)
    story_type:         str = ""
    audience_insights:  str = ""
    emotional_trigger:  str = ""
    twist_type:         str = ""
    avoid_topics:       list[str] = field(default_factory=list)


# ─── Raw signal từ scraper ────────────────────────────────────────
@dataclass
class RawSignal:
    title:        str
    source:       str
    view_count:   int        = 0
    channel_name: str        = ""
    tags:         list[str]  = field(default_factory=list)
    metadata:     dict       = field(default_factory=dict)


# ─── Idea card sau enrichment ─────────────────────────────────────
class TitleOption(BaseModel):
    label: str = Field(description="A / B / C")
    title: str = Field(description="YouTube title")
    hook:  str = Field(description="15-second opening hook")


class IdeaCard(BaseModel):
    raw_signal:        str
    source:            str
    localized_context: str
    title_options:     list[TitleOption] = Field(min_length=3, max_length=3)
    best_title:        str
    hook:              str
    outline:           list[str] = Field(min_length=3, max_length=7)
    script_brief:      str = ""
    tags:              list[str] = Field(min_length=2, max_length=8)


# ─── Scored idea ──────────────────────────────────────────────────
@dataclass
class ScoredIdea:
    idea:              IdeaCard
    trend_score:       float
    competition_score: float
    keyword_score:     float
    final_score:       float
    tier:              str

    @property
    def scores_dict(self) -> dict:
        return {
            "trend":         round(self.trend_score, 1),
            "competition":   round(self.competition_score, 1),
            "keyword_match": round(self.keyword_score, 1),
        }


# ─── Pipeline run stats ───────────────────────────────────────────
@dataclass
class RunStats:
    channel_id:      str
    run_date:        str   = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    raw_count:       int   = 0
    after_filter:    int   = 0
    after_dedup:     int   = 0
    ideas_generated: int   = 0
    tier_a_count:    int   = 0
    total_cost_usd:  float = 0.0
    runtime_seconds: float = 0.0
    errors:          list[str] = field(default_factory=list)