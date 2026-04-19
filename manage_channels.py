"""
manage_channels.py — Quản lý channels từ terminal
Usage:
  python manage_channels.py list
  python manage_channels.py add
  python manage_channels.py edit --name "Tên kênh"
  python manage_channels.py delete --name "Tên kênh"
  python manage_channels.py run --name "Tên kênh" --dry-run --max-signals 5
  python manage_channels.py run --all
"""
import argparse
import asyncio
import json
import os
import sys
from dotenv import load_dotenv

load_dotenv()

from core.config import get_supabase, load_channel_configs


class C:
    BOLD  = '\033[1m'
    BLUE  = '\033[94m'
    GREEN = '\033[92m'
    YELLOW= '\033[93m'
    RED   = '\033[91m'
    END   = '\033[0m'

def bold(s):   return f"{C.BOLD}{s}{C.END}"
def green(s):  return f"{C.GREEN}{s}{C.END}"
def yellow(s): return f"{C.YELLOW}{s}{C.END}"
def red(s):    return f"{C.RED}{s}{C.END}"
def blue(s):   return f"{C.BLUE}{s}{C.END}"


NICHES = {
    "1": {
        "key": "revenge_drama",
        "name": "Revenge / Drama / Karma",
        "content_style": "revenge and karma storytelling",
        "trending_regions": ["US", "UK", "AU"],
        "source_subreddits": ["pettyrevenge", "ProRevenge", "AmItheAsshole", "TrueOffMyChest"],
        "filter_prompt": "ONLY keep if DIRECTLY about: revenge, karma, betrayal, cheating partner, justice served, underdog wins, glow up after being wronged, toxic relationship. REMOVE: sports, music videos, gaming without revenge theme, news, cooking, tech.",
    },
    "2": {
        "key": "finance_business",
        "name": "Finance / Business",
        "content_style": "financial education and business insights",
        "trending_regions": ["US", "UK", "SG"],
        "source_subreddits": ["personalfinance", "investing", "entrepreneur", "business"],
        "filter_prompt": "Keep if about money, investing, business, wealth building, financial freedom. Remove if unrelated to finance.",
    },
    "3": {
        "key": "tech_ai",
        "name": "Tech / AI",
        "content_style": "technology and AI education",
        "trending_regions": ["US", "GB", "IN"],
        "source_subreddits": ["artificial", "MachineLearning", "technology", "ChatGPT"],
        "filter_prompt": "Keep if about AI, technology, software, gadgets, programming, digital trends. Remove if unrelated to tech.",
    },
    "4": {
        "key": "lifestyle_vlog",
        "name": "Lifestyle / Vlog",
        "content_style": "lifestyle, personal development and daily life",
        "trending_regions": ["US", "UK", "AU"],
        "source_subreddits": ["selfimprovement", "productivity", "LifeAdvice", "confession"],
        "filter_prompt": "Keep if about lifestyle, personal growth, relationships, daily life, self improvement. Remove if too niche or technical.",
    },
    "5": {
        "key": "education",
        "name": "Education / Skills",
        "content_style": "educational content and skill building",
        "trending_regions": ["US", "IN", "GB"],
        "source_subreddits": ["learnprogramming", "languagelearning", "GetStudying", "productivity"],
        "filter_prompt": "Keep if educational, teaches a skill, explains a concept, or helps people learn. Remove if entertainment-only.",
    },
    "6": {
        "key": "custom",
        "name": "Custom (tự nhập)",
        "content_style": "",
        "trending_regions": ["US"],
        "source_subreddits": [],
        "filter_prompt": "",
    },
}

LANGUAGES = {
    "1": ("en", "English"),
    "2": ("vi", "Tiếng Việt"),
    "3": ("id", "Bahasa Indonesia"),
    "4": ("th", "Thai"),
    "5": ("ko", "Korean"),
    "6": ("ja", "Japanese"),
    "7": ("es", "Spanish"),
    "8": ("pt", "Portuguese"),
}


def ask(prompt: str, default: str = "") -> str:
    if default:
        result = input(f"{prompt} [{default}]: ").strip()
        return result if result else default
    return input(f"{prompt}: ").strip()


def ask_choice(prompt: str, choices: dict) -> str:
    print(f"\n{bold(prompt)}")
    for k, v in choices.items():
        name = v["name"] if isinstance(v, dict) else v[1]
        print(f"  {blue(k)}. {name}")
    while True:
        choice = input("Chọn số: ").strip()
        if choice in choices:
            return choice
        print(red("Không hợp lệ, thử lại."))


def ask_list(prompt: str, default: list = None) -> list:
    default_str = ", ".join(default) if default else ""
    raw = ask(prompt, default_str)
    return [x.strip() for x in raw.split(",") if x.strip()]


def cmd_list(supabase):
    resp = supabase.table("channels").select(
        "name, niche, language, active, youtube_channel_id, seed_keywords"
    ).order("name").execute()

    if not resp.data:
        print(yellow("Chưa có kênh nào."))
        return

    print(f"\n{bold('DANH SÁCH KÊNH')}")
    print("─" * 70)
    for row in resp.data:
        status = green("● active") if row["active"] else red("○ inactive")
        niche = row.get("niche", "general")
        lang  = row.get("language", "en")
        keywords = ", ".join(row.get("seed_keywords", [])[:3])
        print(
            f"{bold(row['name'])} {status}\n"
            f"  Niche: {blue(niche)} | Lang: {lang} | "
            f"Channel ID: {row['youtube_channel_id']}\n"
            f"  Keywords: {keywords}\n"
        )
    print(f"Tổng: {len(resp.data)} kênh")


def cmd_add(supabase):
    print(f"\n{bold('THÊM KÊNH MỚI')}")
    print("─" * 40)

    name = ask("Tên kênh")
    if not name:
        print(red("Tên kênh không được trống"))
        return

    youtube_id = ask("YouTube Channel ID (UCxxxxxxx)")
    if not youtube_id:
        print(red("Channel ID không được trống"))
        return

    niche_choice = ask_choice("Chọn niche", NICHES)
    niche_data   = NICHES[niche_choice]

    if niche_choice == "6":
        niche_data["key"]           = ask("Niche key ngắn gọn, không dấu cách (vd: space_futurism)", "custom")
        niche_data["name"]          = ask("Niche tên đầy đủ")
        niche_data["content_style"] = ask("Mô tả content style chi tiết")
        niche_data["filter_prompt"] = ask("Filter rule (giữ lại nếu...)")

    lang_choice = ask_choice("Ngôn ngữ output", LANGUAGES)
    language    = LANGUAGES[lang_choice][0]

    print(f"\n{bold('Seed keywords')} (cách nhau bằng dấu phẩy):")
    seed_keywords = ask_list("Keywords", ["revenge story", "karma story"])

    print(f"\n{bold('Competitor Channel IDs')} (UCxxxxxxx, cách nhau bằng dấu phẩy):")
    competitor_ids = ask_list("Competitor IDs", [])

    print(f"\n{bold('CHANNEL DNA')}")
    target_audience  = ask("Target audience", f"People who love {niche_data['name']} content")
    hook_style       = ask("Hook style", "Start with the most shocking moment")
    story_type       = ask("Story type", "Underdog rises, gets justice in the end")
    emotional_trigger= ask("Emotional trigger", "injustice → hope → satisfaction")
    twist_type       = ask("Twist type", "The villain ends up needing the hero")
    audience_insights= ask("Audience insights", "Viewers want to feel validated and inspired")
    tone             = ask("Tone", "engaging, emotional, satisfying")
    avoid_topics     = ask_list("Avoid topics", ["politics", "religion", "explicit content"])

    print(f"\n{bold('XÁC NHẬN THÔNG TIN:')}")
    print(f"  Tên: {name}")
    print(f"  YouTube ID: {youtube_id}")
    print(f"  Niche: {niche_data['key']}")
    print(f"  Language: {language}")
    print(f"  Keywords: {', '.join(seed_keywords)}")
    confirm = ask("\nXác nhận thêm kênh? (y/n)", "y")
    if confirm.lower() != "y":
        print(yellow("Đã hủy."))
        return

    row = {
        "name":               name,
        "youtube_channel_id": youtube_id,
        "seed_keywords":      seed_keywords,
        "competitor_ids":     competitor_ids,
        "language":           language,
        "niche":              niche_data["key"],
        "niche_config": {
            "content_style":     niche_data["content_style"],
            "trending_regions":  niche_data.get("trending_regions", ["US"]),
            "source_subreddits": niche_data.get("source_subreddits", []),
            "filter_prompt":     niche_data["filter_prompt"],
        },
        "tone":               tone,
        "target_audience":    target_audience,
        "hook_style":         hook_style,
        "story_type":         story_type,
        "emotional_trigger":  emotional_trigger,
        "twist_type":         twist_type,
        "audience_insights":  audience_insights,
        "avoid_topics":       avoid_topics,
        "audience_profile": {
            "age_range":      "18-35",
            "interests":      seed_keywords[:5],
            "pain_points":    [],
            "language_style": tone,
        },
        "scoring_weights": {
            "trend":         0.30,
            "competition":   0.45,
            "keyword_match": 0.25,
        },
        "cooldown_days": 30,
        "active":        True,
    }

    try:
        supabase.table("channels").insert(row).execute()
        print(green(f"\n✓ Đã thêm kênh '{name}' thành công!"))
        print(f"  Test: {bold(f'python manage_channels.py run --name \"{name}\" --dry-run --max-signals 5')}")
        print(f"  Thật: {bold(f'python manage_channels.py run --name \"{name}\"')}")
    except Exception as e:
        print(red(f"Lỗi: {e}"))


def cmd_edit(supabase, name: str):
    resp = supabase.table("channels").select("*").eq("name", name).execute()
    if not resp.data:
        print(red(f"Không tìm thấy kênh '{name}'"))
        return

    row = resp.data[0]
    print(f"\n{bold(f'SỬA KÊNH: {name}')}")
    print("Nhấn Enter để giữ nguyên giá trị hiện tại\n")

    updates = {}

    new_keywords = ask_list("Seed keywords", row.get("seed_keywords", []))
    if new_keywords != row.get("seed_keywords"):
        updates["seed_keywords"] = new_keywords

    new_competitors = ask_list("Competitor IDs", row.get("competitor_ids", []))
    if new_competitors != row.get("competitor_ids"):
        updates["competitor_ids"] = new_competitors

    new_target = ask("Target audience", row.get("target_audience", ""))
    if new_target != row.get("target_audience"):
        updates["target_audience"] = new_target

    new_hook = ask("Hook style", row.get("hook_style", ""))
    if new_hook != row.get("hook_style"):
        updates["hook_style"] = new_hook

    new_avoid = ask_list("Avoid topics", row.get("avoid_topics", []))
    if new_avoid != row.get("avoid_topics"):
        updates["avoid_topics"] = new_avoid

    active = ask("Active? (y/n)", "y" if row.get("active") else "n")
    updates["active"] = active.lower() == "y"

    if not updates:
        print(yellow("Không có thay đổi."))
        return

    supabase.table("channels").update(updates).eq("name", name).execute()
    print(green(f"✓ Đã cập nhật kênh '{name}'"))


def cmd_delete(supabase, name: str):
    confirm = ask(f"Xóa kênh '{name}'? Không thể hoàn tác (y/n)", "n")
    if confirm.lower() != "y":
        print(yellow("Đã hủy."))
        return
    supabase.table("channels").update({"active": False}).eq("name", name).execute()
    print(green(f"✓ Đã vô hiệu hóa kênh '{name}'"))


async def cmd_run(supabase, name: str = None, run_all: bool = False, dry_run: bool = False, max_signals: int = 25):
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    from main import run_channel_pipeline
    from output.push import save_run_stats

    configs = load_channel_configs(supabase)

    if not run_all and name:
        configs = [c for c in configs if c.name == name]
        if not configs:
            print(red(f"Không tìm thấy kênh '{name}'"))
            return

    if not configs:
        print(red("Không có kênh active nào."))
        return

    mode = "TEST" if dry_run else "THẬT"
    print(f"\n{bold(f'CHẠY PIPELINE [{mode}] cho {len(configs)} kênh | max {max_signals} signals')}")
    for c in configs:
        print(f"  • {c.name} [{c.niche} | {c.language}]")
    print()

    for config in configs:
        stats = await run_channel_pipeline(
            config, supabase,
            dry_run=dry_run,
            max_signals=max_signals,
        )
        save_run_stats(stats, supabase)
        status = green("✓") if not stats.errors else yellow("⚠")
        print(
            f"\n{status} {bold(config.name)}: "
            f"{stats.ideas_generated} ideas | "
            f"{stats.tier_a_count} Tier A | "
            f"{stats.runtime_seconds:.0f}s"
        )


def main():
    parser = argparse.ArgumentParser(description="YouTube Idea Engine — Channel Manager")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="Xem tất cả kênh")
    sub.add_parser("add", help="Thêm kênh mới")

    edit_p = sub.add_parser("edit", help="Sửa kênh")
    edit_p.add_argument("--name", required=True)

    del_p = sub.add_parser("delete", help="Xóa kênh")
    del_p.add_argument("--name", required=True)

    run_p = sub.add_parser("run", help="Chạy pipeline")
    run_p.add_argument("--name", help="Tên kênh cụ thể")
    run_p.add_argument("--all", action="store_true", help="Chạy tất cả kênh")
    run_p.add_argument("--dry-run", action="store_true", help="Không push output")
    run_p.add_argument("--max-signals", type=int, default=25, help="So signals toi da (test dung 5)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    supabase = get_supabase()

    if args.command == "list":
        cmd_list(supabase)
    elif args.command == "add":
        cmd_add(supabase)
    elif args.command == "edit":
        cmd_edit(supabase, args.name)
    elif args.command == "delete":
        cmd_delete(supabase, args.name)
    elif args.command == "run":
        if not args.name and not args.all:
            print(red("Cần --name hoặc --all"))
            return
        asyncio.run(cmd_run(
            supabase,
            name=args.name,
            run_all=args.all,
            dry_run=args.dry_run,
            max_signals=args.max_signals,
        ))


if __name__ == "__main__":
    main()