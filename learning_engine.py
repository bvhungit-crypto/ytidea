"""
learning_engine.py — Tự học từ performance data trong Google Sheet
Chạy mỗi tuần: python learning_engine.py
Cần ít nhất 5 videos có Views D30 > 0 mới có kết quả tốt
"""
import os
import json
import logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

import gspread
from google.oauth2.service_account import Credentials
from core.config import get_supabase

SHEET_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

COL = {
    "date":            0,
    "tier":            1,
    "score":           2,
    "title_a":         3,
    "title_b":         4,
    "title_c":         5,
    "hook":            6,
    "outline":         7,
    "script_brief":    8,
    "trend":           9,
    "competition":     10,
    "keyword":         11,
    "tags":            12,
    "source":          13,
    "source_url":      14,
    "status":          15,
    "notes":           16,
    "published_url":   17,
    "views_d7":        18,
    "views_d30":       19,
    "ctr":             20,
    "watch_time":      21,
    "retention_chart": 22,
    "learned":         23,
}


def get_sheet_data(channel_name: str) -> list[dict]:
    """Đọc data từ Google Sheet tab của kênh — bỏ qua video đã học."""
    creds = Credentials.from_service_account_file(
        "credentials.json", scopes=SHEET_SCOPES
    )
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(os.environ["GOOGLE_SHEET_ID"])

    try:
        ws = sheet.worksheet(channel_name)
    except gspread.WorksheetNotFound:
        logger.error(f"Tab '{channel_name}' not found in Sheet")
        return []

    rows = ws.get_all_values()
    if len(rows) < 2:
        return []

    data = []
    for row in rows[1:]:
        if len(row) < 20:
            continue

        # Bỏ qua video đã học
        learned = row[COL["learned"]].strip().upper() if len(row) > COL["learned"] else ""
        if learned == "TRUE":
            continue

        try:
            views_d30 = int(str(row[COL["views_d30"]]).replace(",", "").strip() or 0)
            views_d7  = int(str(row[COL["views_d7"]]).replace(",", "").strip() or 0)
            ctr       = float(str(row[COL["ctr"]]).replace("%", "").strip() or 0)
            score     = float(str(row[COL["score"]]).strip() or 0)
        except (ValueError, IndexError):
            continue

        # Chỉ học từ video đã có data thật
        if views_d30 == 0:
            continue

        data.append({
            "date":        row[COL["date"]],
            "tier":        row[COL["tier"]],
            "score":       score,
            "title":       row[COL["title_a"]],
            "tags":        row[COL["tags"]],
            "source":      row[COL["source"]],
            "trend":       float(str(row[COL["trend"]]).strip() or 0),
            "competition": float(str(row[COL["competition"]]).strip() or 0),
            "keyword":     float(str(row[COL["keyword"]]).strip() or 0),
            "views_d7":    views_d7,
            "views_d30":   views_d30,
            "ctr":         ctr,
        })

    logger.info(f"[{channel_name}] Loaded {len(data)} new videos with performance data")
    return data


def analyze_source_performance(data: list[dict]) -> dict:
    """Phân tích nguồn nào cho views cao nhất."""
    sources = {}
    for row in data:
        src = row["source"]
        if src not in sources:
            sources[src] = {"views": [], "ctr": []}
        sources[src]["views"].append(row["views_d30"])
        sources[src]["ctr"].append(row["ctr"])

    result = {}
    for src, metrics in sources.items():
        avg_views = sum(metrics["views"]) / len(metrics["views"])
        avg_ctr   = sum(metrics["ctr"]) / len(metrics["ctr"]) if metrics["ctr"] else 0
        result[src] = {
            "avg_views_d30": round(avg_views),
            "avg_ctr":       round(avg_ctr, 2),
            "count":         len(metrics["views"]),
        }

    logger.info(f"Source performance: {json.dumps(result, indent=2)}")
    return result


def analyze_score_accuracy(data: list[dict]) -> dict:
    """Kiểm tra predicted score có correlate với views không."""
    if len(data) < 5:
        return {}

    sorted_data = sorted(data, key=lambda x: x["score"], reverse=True)
    half        = len(sorted_data) // 2
    high_score  = sorted_data[:half]
    low_score   = sorted_data[half:]

    avg_views_high = sum(r["views_d30"] for r in high_score) / len(high_score)
    avg_views_low  = sum(r["views_d30"] for r in low_score) / len(low_score)

    accuracy = {
        "high_score_avg_views": round(avg_views_high),
        "low_score_avg_views":  round(avg_views_low),
        "score_predicts_views": avg_views_high > avg_views_low,
        "ratio": round(avg_views_high / avg_views_low, 2) if avg_views_low > 0 else 0,
    }

    logger.info(f"Score accuracy: {json.dumps(accuracy, indent=2)}")
    return accuracy


def calculate_optimal_weights(data: list[dict]) -> dict:
    """Tính scoring weights tối ưu dựa trên correlation với views."""
    if len(data) < 10:
        logger.warning("Not enough data to recalibrate weights (need 10+)")
        return {}

    def correlation(x_list, y_list):
        n = len(x_list)
        if n == 0:
            return 0
        mean_x = sum(x_list) / n
        mean_y = sum(y_list) / n
        num    = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_list, y_list))
        den_x  = (sum((x - mean_x) ** 2 for x in x_list)) ** 0.5
        den_y  = (sum((y - mean_y) ** 2 for y in y_list)) ** 0.5
        if den_x * den_y == 0:
            return 0
        return num / (den_x * den_y)

    views    = [r["views_d30"] for r in data]
    trends   = [r["trend"] for r in data]
    comps    = [r["competition"] for r in data]
    keywords = [r["keyword"] for r in data]

    corr_trend   = abs(correlation(trends, views))
    corr_comp    = abs(correlation(comps, views))
    corr_keyword = abs(correlation(keywords, views))

    total = corr_trend + corr_comp + corr_keyword
    if total == 0:
        return {}

    new_weights = {
        "trend":         round(corr_trend / total, 2),
        "competition":   round(corr_comp / total, 2),
        "keyword_match": round(corr_keyword / total, 2),
    }

    # Đảm bảo tổng = 1
    diff = 1.0 - sum(new_weights.values())
    new_weights["trend"] = round(new_weights["trend"] + diff, 2)

    logger.info(f"New optimal weights: {json.dumps(new_weights, indent=2)}")
    return new_weights


def analyze_title_patterns(data: list[dict]) -> dict:
    """Tìm pattern title nào cho views cao."""
    patterns = {
        "has_she":      [],
        "has_he":       [],
        "has_betrayed": [],
        "has_karma":    [],
        "has_revenge":  [],
        "has_number":   [],
        "has_dash":     [],
        "has_boss":     [],
        "has_family":   [],
    }

    for row in data:
        title = row["title"].lower()
        views = row["views_d30"]

        patterns["has_she"].append(views if "she" in title else None)
        patterns["has_he"].append(views if " he " in title else None)
        patterns["has_betrayed"].append(views if "betray" in title else None)
        patterns["has_karma"].append(views if "karma" in title else None)
        patterns["has_revenge"].append(views if "revenge" in title else None)
        patterns["has_number"].append(views if any(c.isdigit() for c in title) else None)
        patterns["has_dash"].append(views if "—" in title or " - " in title else None)
        patterns["has_boss"].append(views if "boss" in title else None)
        patterns["has_family"].append(views if any(w in title for w in ["mom", "dad", "sister", "brother", "family", "parent"]) else None)

    result = {}
    for pattern, views_list in patterns.items():
        valid = [v for v in views_list if v is not None]
        if valid:
            result[pattern] = {
                "avg_views": round(sum(valid) / len(valid)),
                "count":     len(valid),
            }

    result = dict(sorted(result.items(), key=lambda x: x[1]["avg_views"], reverse=True))
    logger.info(f"Title patterns: {json.dumps(result, indent=2)}")
    return result


def build_smart_prompt_additions(
    title_patterns: dict,
    source_performance: dict,
) -> str:
    """Tạo thêm instructions cho enrichment prompt dựa trên data thật."""
    additions = []

    # 1. Title patterns perform tốt nhất
    if title_patterns:
        top_patterns  = list(title_patterns.items())[:3]
        pattern_hints = []
        for pattern, metrics in top_patterns:
            if metrics["avg_views"] > 10000:
                if pattern == "has_she":
                    pattern_hints.append("start with 'She Was' or 'She Did'")
                elif pattern == "has_he":
                    pattern_hints.append("start with 'He Was' or 'He Did'")
                elif pattern == "has_betrayed":
                    pattern_hints.append("include betrayal/betrayed in title")
                elif pattern == "has_karma":
                    pattern_hints.append("include karma in title")
                elif pattern == "has_dash":
                    pattern_hints.append("use em dash (—) to create cliffhanger")
                elif pattern == "has_family":
                    pattern_hints.append("include family relationship (mom/dad/sister/brother)")
                elif pattern == "has_boss":
                    pattern_hints.append("include workplace/boss conflict")
                elif pattern == "has_number":
                    pattern_hints.append("include specific numbers ($, years, times)")

        if pattern_hints:
            additions.append(
                "PROVEN HIGH-PERFORMING TITLE PATTERNS (based on real channel data):\n" +
                "\n".join(f"- {p}" for p in pattern_hints)
            )

    # 2. Best source insights
    if source_performance:
        best_source = max(
            source_performance.items(),
            key=lambda x: x[1]["avg_views_d30"]
        )
        src_name, src_metrics = best_source
        if src_metrics["avg_views_d30"] > 0:
            additions.append(
                f"DATA INSIGHT: Stories from '{src_name}' source average "
                f"{src_metrics['avg_views_d30']:,} views — prioritize adapting this content style."
            )

    return "\n\n".join(additions)


def update_enrichment_prompt(
    channel_name: str,
    supabase,
    title_patterns: dict,
    source_performance: dict,
):
    """Tự động update niche_config với learned insights để Claude dùng."""
    if not title_patterns and not source_performance:
        return

    smart_additions = build_smart_prompt_additions(title_patterns, source_performance)
    if not smart_additions:
        return

    # Lấy niche_config hiện tại
    resp = supabase.table("channels").select("niche_config").eq("name", channel_name).execute()
    if not resp.data:
        return

    current_niche_config = resp.data[0].get("niche_config", {})

    # Thêm learned insights
    current_niche_config["learned_insights"] = smart_additions
    current_niche_config["last_learned"]     = datetime.now().isoformat()

    supabase.table("channels").update({
        "niche_config": current_niche_config,
    }).eq("name", channel_name).execute()

    logger.info(f"✓ Updated enrichment prompt for '{channel_name}'")
    logger.info(f"  Smart additions:\n{smart_additions}")


def update_channel_config(
    channel_name: str,
    supabase,
    new_weights: dict,
    source_performance: dict,
    title_patterns: dict,
    score_accuracy: dict,
):
    """Cập nhật toàn bộ config kênh dựa trên learning."""
    updates = {}

    # Update scoring weights
    if new_weights:
        updates["scoring_weights"] = new_weights
        logger.info(f"Updating scoring weights: {new_weights}")

    # Lưu insights để tracking
    insights = {
        "last_updated":       datetime.now().isoformat(),
        "source_performance": source_performance,
        "title_patterns":     title_patterns,
        "score_accuracy":     score_accuracy,
        "top_sources": sorted(
            source_performance.items(),
            key=lambda x: x[1]["avg_views_d30"],
            reverse=True
        )[:3] if source_performance else [],
    }
    updates["audience_insights"] = json.dumps(insights, ensure_ascii=False)

    if updates:
        supabase.table("channels").update(updates).eq("name", channel_name).execute()
        logger.info(f"✓ Updated config for '{channel_name}'")

    # Tự động update enrichment prompt
    update_enrichment_prompt(channel_name, supabase, title_patterns, source_performance)


def mark_as_learned(channel_name: str):
    """Đánh dấu TRUE vào cột Learned cho các video đã có Views D30 > 0."""
    creds = Credentials.from_service_account_file(
        "credentials.json", scopes=SHEET_SCOPES
    )
    gc    = gspread.authorize(creds)
    sheet = gc.open_by_key(os.environ["GOOGLE_SHEET_ID"])
    ws    = sheet.worksheet(channel_name)

    rows        = ws.get_all_values()
    learned_col = COL["learned"] + 1  # gspread dùng index 1

    updates = []
    for i, row in enumerate(rows[1:], start=2):
        if len(row) < COL["views_d30"] + 1:
            continue

        views_d30 = str(row[COL["views_d30"]]).replace(",", "").strip()
        learned   = row[COL["learned"]].strip().upper() if len(row) > COL["learned"] else ""

        # Chỉ đánh dấu video có data thật và chưa được đánh dấu
        if views_d30.isdigit() and int(views_d30) > 0 and learned != "TRUE":
            updates.append({
                "range":  f"{chr(64 + learned_col)}{i}",
                "values": [["TRUE"]]
            })

    if updates:
        ws.batch_update(updates)
        logger.info(f"Marked {len(updates)} videos as learned")
    else:
        logger.info("No new videos to mark")


def print_report(
    channel_name: str,
    data: list[dict],
    source_performance: dict,
    title_patterns: dict,
    score_accuracy: dict,
    new_weights: dict,
):
    """In báo cáo learning."""
    print(f"\n{'='*60}")
    print(f"LEARNING REPORT — {channel_name}")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    print(f"Videos analyzed: {len(data)}")

    if source_performance:
        print(f"\n📊 SOURCE PERFORMANCE:")
        for src, metrics in sorted(
            source_performance.items(),
            key=lambda x: x[1]["avg_views_d30"],
            reverse=True
        ):
            print(
                f"  {src:20} avg {metrics['avg_views_d30']:>8,} views | "
                f"CTR {metrics['avg_ctr']:>5}% | {metrics['count']} videos"
            )

    if title_patterns:
        print(f"\n🎯 BEST TITLE PATTERNS (top 5):")
        for i, (pattern, metrics) in enumerate(list(title_patterns.items())[:5]):
            print(f"  {i+1}. {pattern:20} avg {metrics['avg_views']:>8,} views ({metrics['count']} videos)")

    if score_accuracy:
        predicts = "✅ YES" if score_accuracy.get("score_predicts_views") else "❌ NO"
        print(f"\n🎲 SCORE ACCURACY: {predicts}")
        print(f"  High score → avg {score_accuracy.get('high_score_avg_views', 0):,} views")
        print(f"  Low score  → avg {score_accuracy.get('low_score_avg_views', 0):,} views")
        print(f"  Ratio: {score_accuracy.get('ratio', 0)}x")

    if new_weights:
        print(f"\n⚙️  NEW SCORING WEIGHTS (updated in Supabase):")
        for k, v in new_weights.items():
            print(f"  {k}: {v}")
    else:
        print(f"\n⚙️  WEIGHTS: Not enough data (need 10+ videos with Views D30)")

    print(f"\n{'='*60}\n")


def run_learning(channel_name: str = None):
    """Chạy learning engine cho 1 kênh hoặc tất cả."""
    supabase = get_supabase()

    if channel_name:
        resp = supabase.table("channels").select("*").eq("name", channel_name).eq("active", True).execute()
    else:
        resp = supabase.table("channels").select("*").eq("active", True).execute()

    channels = resp.data
    if not channels:
        logger.error("No channels found")
        return

    for channel in channels:
        name = channel["name"]
        logger.info(f"\nProcessing: {name}")

        # Lấy data mới từ Sheet (bỏ qua đã học)
        data = get_sheet_data(name)

        if len(data) < 5:
            logger.warning(
                f"[{name}] Only {len(data)} new videos with data — "
                f"need at least 5 for analysis"
            )
            continue

        # Phân tích
        source_perf    = analyze_source_performance(data)
        score_acc      = analyze_score_accuracy(data)
        new_weights    = calculate_optimal_weights(data)
        title_patterns = analyze_title_patterns(data)

        # In báo cáo
        print_report(name, data, source_perf, title_patterns, score_acc, new_weights)

        # Cập nhật config + enrichment prompt
        update_channel_config(
            name, supabase,
            new_weights, source_perf, title_patterns, score_acc
        )

        # Đánh dấu đã học
        mark_as_learned(name)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="YouTube Idea Engine — Learning Engine")
    parser.add_argument("--name", help="Tên kênh cụ thể (bỏ trống = tất cả kênh)")
    args = parser.parse_args()

    run_learning(channel_name=args.name)