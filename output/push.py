"""
output/push.py — Tầng 5+6: Lưu Supabase, push Google Sheet, gửi Telegram
"""
import os
import json
import logging
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from supabase import Client
from core.models import ScoredIdea, ChannelConfig, RunStats

logger = logging.getLogger(__name__)

SHEET_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_sheet_client():
    creds = Credentials.from_service_account_file(
        "credentials.json", scopes=SHEET_SCOPES
    )
    return gspread.authorize(creds)


def save_ideas_to_supabase(
    scored_ideas: list[tuple[ScoredIdea, str]],
    config: ChannelConfig,
    supabase: Client,
    top_n: int = 7,
) -> list[str]:
    idea_ids = []
    tier_order = {"A": 0, "B": 1, "C": 2}
    to_save = sorted(
        scored_ideas[:top_n * 2],
        key=lambda x: (tier_order[x[0].tier], -x[0].final_score)
    )[:top_n]

    for si, source_url in to_save:
        idea = si.idea
        try:
            row = {
                "channel_id":        config.channel_id,
                "source":            idea.source,
                "raw_signal":        idea.raw_signal,
                "title_options":     [t.model_dump() for t in idea.title_options],
                "best_title":        idea.best_title,
                "hook":              idea.hook,
                "outline":           idea.outline,
                "localized_context": idea.localized_context,
                "tags":              idea.tags,
                "scores":            si.scores_dict,
                "final_score":       si.final_score,
                "tier":              si.tier,
                "status":            "pending",
            }
            resp = supabase.table("ideas").insert(row).execute()
            idea_id = resp.data[0]["idea_id"]
            idea_ids.append(idea_id)
        except Exception as e:
            logger.error(f"Supabase insert error: {e}")

    logger.info(f"Saved {len(idea_ids)} ideas to Supabase")
    return idea_ids


def save_run_stats(stats: RunStats, supabase: Client):
    try:
        supabase.table("pipeline_runs").insert({
            "channel_id":        stats.channel_id,
            "run_date":          stats.run_date,
            "status":            "success" if not stats.errors else "partial",
            "raw_signals_count": stats.raw_count,
            "after_filter":      stats.after_filter,
            "after_dedup":       stats.after_dedup,
            "ideas_generated":   stats.ideas_generated,
            "ideas_tier_a":      stats.tier_a_count,
            "runtime_seconds":   round(stats.runtime_seconds, 2),
            "error_message":     "\n".join(stats.errors) if stats.errors else None,
            "finished_at":       datetime.now().isoformat(),
        }).execute()
    except Exception as e:
        logger.error(f"Save run stats error: {e}")


def push_to_google_sheet(
    scored_ideas: list[tuple[ScoredIdea, str]],
    config: ChannelConfig,
    top_n: int = 7,
):
    try:
        gc    = get_sheet_client()
        sheet = gc.open_by_key(os.environ["GOOGLE_SHEET_ID"])
        today = datetime.now().strftime("%Y-%m-%d")

        try:
            ws = sheet.worksheet(config.name)
        except gspread.WorksheetNotFound:
            ws = sheet.add_worksheet(title=config.name, rows=1000, cols=30)
            ws.append_row([
                "Date", "Tier", "Score",
                "Title A", "Title B", "Title C",
                "Hook", "Outline", "Script Brief",
                "Trend", "Competition", "Keyword",
                "Tags", "Source", "Source URL",
                "Status", "Notes",
                "Published URL", "Views D7", "Views D30",
                "CTR %", "Avg Watch Time", "Retention Chart URL", "Learned",
            ], value_input_option="USER_ENTERED")
            ws.format("A1:X1", {
                "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.6},
                "textFormat": {
                    "bold": True,
                    "foregroundColor": {"red": 1, "green": 1, "blue": 1}
                },
            })
            ws.freeze(rows=1)

        top = sorted(
            scored_ideas,
            key=lambda x: (0 if x[0].tier == "A" else 1, -x[0].final_score)
        )[:top_n]

        rows = []
        for si, source_url in top:
            idea            = si.idea
            titles          = {t.label: t.title for t in idea.title_options}
            outline_summary = " → ".join(idea.outline[:3]) + "..."
            script_brief    = getattr(idea, "script_brief", "")
            rows.append([
                today, si.tier, si.final_score,
                titles.get("A", ""),
                titles.get("B", ""),
                titles.get("C", ""),
                idea.hook, outline_summary, script_brief,
                si.trend_score, si.competition_score, si.keyword_score,
                ", ".join(idea.tags),
                idea.source,
                source_url,
                "Pending", "",
                "", "", "", "", "", "", "",
            ])

        ws.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info(f"Pushed {len(rows)} ideas to Sheet tab '{config.name}'")

    except Exception as e:
        logger.error(f"Google Sheet push error: {e}")


async def send_telegram_digest(
    scored_ideas: list[tuple[ScoredIdea, str]],
    config: ChannelConfig,
    run_stats: RunStats,
    top_n: int = 7,
):
    try:
        import httpx
        bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
        chat_id   = os.environ["TELEGRAM_CHAT_ID"]
        today     = datetime.now().strftime("%d/%m/%Y")
        base_url  = f"https://api.telegram.org/bot{bot_token}"

        top = sorted(
            scored_ideas,
            key=lambda x: (0 if x[0].tier == "A" else 1, -x[0].final_score)
        )[:top_n]

        tier_a = sum(1 for s, _ in top if s.tier == "A")

        header = (
            f"📺 *YouTube Ideas — {config.name}*\n"
            f"📅 {today} | 🔥 {tier_a} Tier A | "
            f"⏱ {run_stats.runtime_seconds:.0f}s\n"
            f"─────────────────────────\n"
            f"📥 Signals: {run_stats.raw_count} → "
            f"✅ Clean: {run_stats.after_filter} → "
            f"💡 Ideas: {run_stats.ideas_generated}\n"
            f"─────────────────────────"
        )

        async with httpx.AsyncClient() as client:
            await client.post(f"{base_url}/sendMessage", json={
                "chat_id":    chat_id,
                "text":       header,
                "parse_mode": "Markdown",
            })

            for i, (si, source_url) in enumerate(top, 1):
                idea       = si.idea
                score_bar  = "█" * int(si.final_score / 10) + "░" * (10 - int(si.final_score / 10))
                tier_emoji = {"A": "🔥", "B": "⭐", "C": "💤"}.get(si.tier, "")
                url_text   = f"\n🔗 {source_url}" if source_url else ""
                text = (
                    f"{tier_emoji} *#{i} — Tier {si.tier} | {si.final_score}/100*\n"
                    f"`{score_bar}`\n\n"
                    f"📝 *{idea.best_title}*\n\n"
                    f"🎬 {idea.hook[:120]}"
                    f"{url_text}"
                )
                try:
                    await client.post(f"{base_url}/sendMessage", json={
                        "chat_id":    chat_id,
                        "text":       text,
                        "parse_mode": "Markdown",
                    })
                except Exception as e:
                    logger.warning(f"Telegram idea #{i} error: {e}")

            sheet_url = f"https://docs.google.com/spreadsheets/d/{os.environ.get('GOOGLE_SHEET_ID', '')}"
            await client.post(f"{base_url}/sendMessage", json={
                "chat_id": chat_id,
                "text":    f"─────────────────────────\n👉 Review: {sheet_url}",
            })

        logger.info(f"Telegram digest sent: {len(top)} ideas")

    except Exception as e:
        logger.error(f"Telegram send error: {e}")