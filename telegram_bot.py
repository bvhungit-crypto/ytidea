"""
telegram_bot.py — Telegram bot với inline approve/reject buttons
Chạy song song với pipeline: python telegram_bot.py
"""
import os
import json
import logging
import asyncio
import httpx
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
BASE_URL  = f"https://api.telegram.org/bot{BOT_TOKEN}"


# ── Gửi tin nhắn ──────────────────────────────────────────────────
async def send_message(text: str, reply_markup: dict = None) -> dict:
    payload = {
        "chat_id":    CHAT_ID,
        "text":       text,
        "parse_mode": "Markdown",
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)

    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{BASE_URL}/sendMessage", json=payload)
        return resp.json()


async def send_idea_with_buttons(
    idea_id: str,
    channel_name: str,
    tier: str,
    score: float,
    title_a: str,
    title_b: str,
    title_c: str,
    hook: str,
    script_brief: str,
    source_url: str,
    rank: int,
) -> dict:
    """Gửi idea với inline buttons Approve/Reject."""

    score_bar = "█" * int(score / 10) + "░" * (10 - int(score / 10))
    tier_emoji = {"A": "🔥", "B": "⭐", "C": "💤"}.get(tier, "")
    url_text = f"\n🔗 Source: {source_url}" if source_url else ""

    text = (
        f"{tier_emoji} *#{rank} — Tier {tier} | Score: {score}/100*\n"
        f"`{score_bar}`\n\n"
        f"📝 *Titles:*\n"
        f"  A. {title_a}\n"
        f"  B. {title_b}\n"
        f"  C. {title_c}\n\n"
        f"🎬 *Hook:* {hook[:120]}{'...' if len(hook) > 120 else ''}\n\n"
        f"📄 *Script Brief:* {script_brief[:200]}{'...' if len(script_brief) > 200 else ''}"
        f"{url_text}"
    )

    reply_markup = {
        "inline_keyboard": [[
            {
                "text":          "✅ Approve",
                "callback_data": f"approve:{idea_id}"
            },
            {
                "text":          "❌ Reject",
                "callback_data": f"reject:{idea_id}"
            },
            {
                "text":          "🔄 Maybe",
                "callback_data": f"maybe:{idea_id}"
            },
        ]]
    }

    return await send_message(text, reply_markup)


# ── Xử lý callback khi bấm nút ───────────────────────────────────
async def answer_callback(callback_query_id: str, text: str):
    async with httpx.AsyncClient() as client:
        await client.post(f"{BASE_URL}/answerCallbackQuery", json={
            "callback_query_id": callback_query_id,
            "text":              text,
            "show_alert":        False,
        })


async def edit_message_reply_markup(
    message_id: int,
    new_text: str,
):
    """Xóa buttons sau khi đã bấm."""
    async with httpx.AsyncClient() as client:
        await client.post(f"{BASE_URL}/editMessageText", json={
            "chat_id":    CHAT_ID,
            "message_id": message_id,
            "text":       new_text,
            "parse_mode": "Markdown",
        })


async def handle_callback(callback_query: dict, supabase):
    """Xử lý khi user bấm Approve/Reject/Maybe."""
    query_id   = callback_query["id"]
    data       = callback_query.get("data", "")
    message    = callback_query.get("message", {})
    message_id = message.get("message_id")
    user       = callback_query.get("from", {})
    username   = user.get("username") or user.get("first_name", "Unknown")

    if ":" not in data:
        return

    action, idea_id = data.split(":", 1)

    # Map action → status
    status_map = {
        "approve": "approved",
        "reject":  "rejected",
        "maybe":   "maybe",
    }
    emoji_map = {
        "approve": "✅",
        "reject":  "❌",
        "maybe":   "🔄",
    }

    status = status_map.get(action)
    emoji  = emoji_map.get(action, "")

    if not status:
        return

    try:
        # Update status trong Supabase
        supabase.table("ideas").update({
            "status":      status,
            "approved_by": username,
        }).eq("idea_id", idea_id).execute()

        # Trả lời callback
        await answer_callback(query_id, f"{emoji} {status.capitalize()}!")

        # Xóa buttons, thêm status vào message
        original_text = message.get("text", "")
        new_text = f"{original_text}\n\n{emoji} *{status.upper()}* by @{username}"
        await edit_message_reply_markup(message_id, new_text)

        logger.info(f"Idea {idea_id[:8]}... → {status} by {username}")

    except Exception as e:
        logger.error(f"Handle callback error: {e}")
        await answer_callback(query_id, "❌ Error, try again")


# ── Long polling ──────────────────────────────────────────────────
async def run_bot(supabase):
    """Chạy bot liên tục nhận updates."""
    logger.info("Telegram bot started — waiting for button presses...")
    offset = 0

    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            try:
                resp = await client.get(
                    f"{BASE_URL}/getUpdates",
                    params={
                        "offset":          offset,
                        "timeout":         25,
                        "allowed_updates": ["callback_query"],
                    }
                )
                data = resp.json()

                if not data.get("ok"):
                    await asyncio.sleep(5)
                    continue

                for update in data.get("result", []):
                    offset = update["update_id"] + 1

                    if "callback_query" in update:
                        await handle_callback(update["callback_query"], supabase)

            except httpx.TimeoutException:
                continue
            except Exception as e:
                logger.error(f"Bot error: {e}")
                await asyncio.sleep(5)


# ── Gửi digest với buttons ────────────────────────────────────────
async def send_digest_with_buttons(
    scored_ideas: list,
    config,
    run_stats,
    supabase,
    top_n: int = 7,
):
    """Thay thế send_telegram_digest — gửi ideas với inline buttons."""
    from datetime import datetime

    today   = datetime.now().strftime("%d/%m/%Y")
    top     = sorted(
        scored_ideas,
        key=lambda x: (0 if x[0].tier == "A" else 1, -x[0].final_score)
    )[:top_n]

    tier_a = sum(1 for s, _ in top if s.tier == "A")

    # Gửi header
    header = (
        f"📺 *YouTube Ideas — {config.name}*\n"
        f"📅 {today} | 🔥 {tier_a} Tier A | "
        f"⏱ {run_stats.runtime_seconds:.0f}s\n"
        f"─────────────────────────\n"
        f"📥 Signals: {run_stats.raw_count} → "
        f"✅ Clean: {run_stats.after_filter} → "
        f"💡 Ideas: {run_stats.ideas_generated}\n"
        f"─────────────────────────\n"
        f"👇 Bấm Approve/Reject cho từng idea:"
    )
    await send_message(header)

    # Lấy idea_ids từ Supabase
    resp = supabase.table("ideas").select("idea_id, best_title").eq(
        "channel_id", config.channel_id
    ).eq("status", "pending").order("created_at", desc=True).limit(top_n).execute()

    idea_ids = {row["best_title"]: row["idea_id"] for row in resp.data}

    # Gửi từng idea với buttons
    for i, (si, source_url) in enumerate(top, 1):
        idea    = si.idea
        titles  = {t.label: t.title for t in idea.title_options}
        idea_id = idea_ids.get(idea.best_title, "unknown")

        try:
            await send_idea_with_buttons(
                idea_id=      idea_id,
                channel_name= config.name,
                tier=         si.tier,
                score=        si.final_score,
                title_a=      titles.get("A", ""),
                title_b=      titles.get("B", ""),
                title_c=      titles.get("C", ""),
                hook=         idea.hook,
                script_brief= getattr(idea, "script_brief", ""),
                source_url=   source_url,
                rank=         i,
            )
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning(f"Send idea #{i} error: {e}")

    # Footer
    sheet_url = f"https://docs.google.com/spreadsheets/d/{os.environ.get('GOOGLE_SHEET_ID', '')}"
    await send_message(
        f"─────────────────────────\n"
        f"👉 Review in Google Sheet:\n{sheet_url}"
    )

    logger.info(f"Digest with buttons sent: {len(top)} ideas")


if __name__ == "__main__":
    from core.config import get_supabase
    supabase = get_supabase()
    asyncio.run(run_bot(supabase))