"""
core/config.py — Load channel config từ Supabase + setup clients
"""
import os
import logging
from dotenv import load_dotenv
from supabase import create_client, Client
from core.models import ChannelConfig

load_dotenv()
logger = logging.getLogger(__name__)


def get_supabase() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def load_channel_configs(supabase: Client) -> list[ChannelConfig]:
    """Load tất cả active channels từ Supabase."""
    resp = supabase.table("channels").select("*").eq("active", True).execute()
    configs = []
    for row in resp.data:
        configs.append(ChannelConfig(
            channel_id=         row["channel_id"],
            name=               row["name"],
            youtube_channel_id= row["youtube_channel_id"],
            seed_keywords=      row["seed_keywords"],
            competitor_ids=     row["competitor_ids"],
            tone=               row["tone"],
            audience_profile=   row["audience_profile"],
            scoring_weights=    row["scoring_weights"],
            topic_ban_list=     row["topic_ban_list"],
            cooldown_days=      row["cooldown_days"],
            language=           row.get("language", "en"),
            niche=              row.get("niche", "general"),
            niche_config=       row.get("niche_config", {}),
            target_audience=    row.get("target_audience", ""),
            hook_style=         row.get("hook_style", ""),
            top_videos=         row.get("top_videos", []),
            story_type=         row.get("story_type", ""),
            audience_insights=  row.get("audience_insights", ""),
            emotional_trigger=  row.get("emotional_trigger", ""),
            twist_type=         row.get("twist_type", ""),
            avoid_topics=       row.get("avoid_topics", []),
        ))
    logger.info(f"Loaded {len(configs)} active channels")
    return configs


def log_cost(
    supabase: Client,
    channel_id: str,
    stage: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    youtube_units: int = 0,
) -> float:
    pricing = {
        "claude-haiku-4-5-20251001": (0.80,  4.00),
        "claude-sonnet-4-6":         (3.00, 15.00),
    }
    in_price, out_price = pricing.get(model, (3.00, 15.00))
    cost = (input_tokens * in_price + output_tokens * out_price) / 1_000_000

    supabase.table("api_quota_log").insert({
        "channel_id":     channel_id,
        "pipeline_stage": stage,
        "model":          model,
        "input_tokens":   input_tokens,
        "output_tokens":  output_tokens,
        "cost_usd":       round(cost, 6),
        "youtube_units":  youtube_units,
    }).execute()

    return cost