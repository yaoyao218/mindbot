"""
週報排程
- 每週一凌晨 3 點執行（處理上週 Mon-Sun）
- AI 生成摘要 + 情緒統計 + 主題
- 組成 WeeklyReport → Redis 待領
- 刪除 PostgreSQL 原始資料
"""
import json, asyncio
from datetime import datetime, date, timedelta
from typing import Optional

from services.db_persistent import (
    get_users_in_range, get_messages_in_range,
    get_psych_in_range, delete_messages_in_range, save_archive
)
from services.redis_client import put_weekly_report
from services.llm import call_api

# ── 週 ID 工具 ────────────────────────────────────────────
def get_week_id(d: date) -> str:
    """回傳 ISO 週 ID，例：2025-W03"""
    return f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"

def get_last_week_range() -> tuple[date, date, str]:
    """回傳上週的 (start, end, week_id)，Mon-Sun"""
    today     = date.today()
    last_mon  = today - timedelta(days=today.weekday() + 7)
    last_sun  = last_mon + timedelta(days=6)
    week_id   = get_week_id(last_mon)
    return last_mon, last_sun, week_id

# ── 統計運算（本地，不走 AI）─────────────────────────────
def compute_stats(messages: list[dict], psych_rows: list[dict]) -> dict:
    user_msgs = [m for m in messages if m["role"] == "user"]

    # 情緒曲線：每筆 psych 的 arousal + 時間
    arousal_curve = [
        {"t": r["created_at"], "v": r["arousal"]}
        for r in psych_rows if r.get("arousal")
    ]

    # 情緒分佈
    emotion_counts: dict[str, int] = {}
    for r in psych_rows:
        e = r.get("emotion")
        if e:
            emotion_counts[e] = emotion_counts.get(e, 0) + 1

    # 平均 arousal
    arousals = [r["arousal"] for r in psych_rows if r.get("arousal")]
    avg_arousal = round(sum(arousals) / len(arousals), 2) if arousals else None

    # 每日訊息數
    daily: dict[str, int] = {}
    for m in user_msgs:
        day = m["created_at"][:10]
        daily[day] = daily.get(day, 0) + 1

    return {
        "total_turns":    len(messages),
        "user_msg_count": len(user_msgs),
        "avg_arousal":    avg_arousal,
        "arousal_curve":  arousal_curve,
        "emotion_counts": emotion_counts,
        "daily_counts":   daily,
    }

# ── AI 摘要 ───────────────────────────────────────────────
async def generate_weekly_summary(
    messages: list[dict], week_id: str
) -> tuple[str, list[str], str]:
    """回傳 (summary, themes, growth_note)"""
    user_texts = [m["content"] for m in messages if m["role"] == "user"]
    sample     = "\n".join(user_texts[:40])

    prompt = f"""以下是用戶在 {week_id} 的心事日記對話（僅用戶訊息）：

{sample}

請以繁體中文回覆，僅輸出 JSON，不要有任何前言或 markdown：
{{
  "summary": "兩到三句話，溫暖中性的本週情緒摘要",
  "themes": ["本週主要困擾，最多3個，每個不超過6字"],
  "growth_note": "一句話，觀察用戶本週的細微轉變或值得肯定之處"
}}"""

    raw   = await call_api(prompt, max_tokens=500)
    if not raw:
        raise ValueError("empty response from LLM")
    clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    data  = json.loads(clean)

    return (
        data.get("summary", ""),
        data.get("themes", []),
        data.get("growth_note", ""),
    )

# ── 單一用戶週報產生 ──────────────────────────────────────
_LOW_ENGAGEMENT_TAROT_POOL = [
    ("WHEEL_OF_FORTUNE_REVERSED", "命運之輪・逆位", "靜待時機，內在正在蓄積力量"),
    ("HIGH_PRIESTESS", "女祭司", "沉默中自有深邃的智慧"),
    ("HERMIT", "隱者", "獨處是為了更清醒地回到自己"),
    ("MOON", "月亮", "在模糊之中，感受也是真實的"),
]

async def build_weekly_report(
    user_id: str, start: date, end: date, week_id: str
) -> Optional[dict]:
    messages   = await get_messages_in_range(user_id, start, end)
    psych_rows = await get_psych_in_range(user_id, start, end)

    if not messages:
        # 低度參與降級週報：不回傳 None，改回傳有溫度的空週結構
        import random as _random
        _tarot_key, _tarot_name, _tarot_meaning = _random.choice(_LOW_ENGAGEMENT_TAROT_POOL)
        fallback_report = {
            "week_id":     week_id,
            "user_id":     user_id,
            "start":       start.isoformat(),
            "end":         end.isoformat(),
            "summary":     "這週的你選擇把心事暫時闔上，給了自己一段安靜沉澱的空間。這也是很棒的自我調節方式。",
            "themes":      [],
            "growth_note": "在無言的留白中，內心正在靜靜蓄積重新出發的能量。",
            "end_quote":   "有時候，什麼都不說，也是一種對自己的溫柔。",
            "raw_count":   0,
            "created_at":  datetime.utcnow().isoformat(),
            "is_low_engagement": True,
            "psych_context": {
                "dialogue_insight": "在無言的留白中，內心正在靜靜蓄積重新出發的能量。",
                "tarot_card":    _tarot_key,
                "tarot_name_zh": _tarot_name,
                "tarot_meaning": _tarot_meaning,
                "end_quote":     "有時候，什麼都不說，也是一種對自己的溫柔。",
                "quote_author":  "心事日記",
            },
            "stats": {
                "total_turns": 0, "user_msg_count": 0,
                "avg_arousal": None, "arousal_curve": [],
                "emotion_counts": {}, "daily_counts": {},
            },
        }
        try:
            await save_archive(
                user_id, week_id,
                fallback_report["summary"],
                stats={**fallback_report["stats"],
                       "themes": [], "growth_note": fallback_report["growth_note"],
                       "start": start.isoformat(), "end": end.isoformat(),
                       "is_low_engagement": True},
                raw_count=0,
            )
        except Exception as e:
            print(f"[weekly] save_archive (low-engagement) failed for {user_id}: {e}")
        try:
            await put_weekly_report(user_id, week_id, fallback_report)
        except Exception:
            pass
        print(f"[weekly] {user_id} {week_id}: no messages, low-engagement report saved")
        return fallback_report

    # 統計（本地運算）
    stats = compute_stats(messages, psych_rows)

    # AI 摘要
    try:
        summary, themes, growth_note = await generate_weekly_summary(messages, week_id)
    except Exception as e:
        print(f"[weekly] AI failed for {user_id} {week_id}: {e}")
        summary     = "本週摘要生成失敗，統計資料仍完整保留。"
        themes      = []
        growth_note = ""

    # 取當週最後一筆收尾語錄
    end_quote = next(
        (r["end_quote"] for r in reversed(psych_rows) if r.get("end_quote")),
        None
    )

    report = {
        "week_id":     week_id,
        "user_id":     user_id,
        "start":       start.isoformat(),
        "end":         end.isoformat(),
        "summary":     summary,
        "themes":      themes,
        "growth_note": growth_note,
        "end_quote":   end_quote,
        "stats":       stats,
        "raw_count":   len(messages),
        "created_at":  datetime.utcnow().isoformat(),
    }

    # 存 PostgreSQL（永久）
    try:
        # psych_context：取當週最後一筆有 dialogue_insight 或 quote_author 的記錄
        _pc_quote_author     = None
        _pc_dialogue_insight = None
        _pc_tarot_card       = None
        for row in reversed(psych_rows):
            if row.get("end_quote") and not end_quote:
                end_quote = row["end_quote"]
            if row.get("quote_author") and not _pc_quote_author:
                _pc_quote_author = row["quote_author"]
            if row.get("dialogue_insight") and not _pc_dialogue_insight:
                _pc_dialogue_insight = row["dialogue_insight"]
            if row.get("tarot_card") and not _pc_tarot_card:
                _pc_tarot_card = row["tarot_card"]
            if all([end_quote, _pc_quote_author, _pc_dialogue_insight, _pc_tarot_card]):
                break

        await save_archive(
            user_id, week_id, summary,
            stats={**stats,
                   "themes": themes, "growth_note": growth_note,
                   "start": start.isoformat(), "end": end.isoformat(),
                   "end_quote":        end_quote,
                   "quote_author":     _pc_quote_author,
                   "dialogue_insight": _pc_dialogue_insight,
                   "tarot_card":       _pc_tarot_card},
            raw_count=len(messages),
        )
    except Exception as e:
        print(f"[weekly] save_archive failed: {e}")

    # 存 Redis（如有設定，讓網站即時 pop）
    try:
        await put_weekly_report(user_id, week_id, report)
    except Exception:
        pass  # Redis 未設定時忽略

    # 刪除原始資料
    deleted = await delete_messages_in_range(user_id, start, end)
    print(f"[weekly] {user_id} {week_id}: {deleted} msgs deleted, report saved")

    return report

# ── 全量排程入口 ──────────────────────────────────────────
async def run_weekly_archive() -> None:
    """
    Railway Cron：0 19 * * 0（UTC 週日 19:00 = 台灣週一凌晨 3:00）
    """
    start, end, week_id = get_last_week_range()
    print(f"[weekly] Processing {week_id} ({start} ~ {end})")

    users = await get_users_in_range(start, end)
    print(f"[weekly] {len(users)} users to process")

    sem = asyncio.Semaphore(5)

    async def safe_build(uid: str):
        async with sem:
            try:
                await build_weekly_report(uid, start, end, week_id)
            except Exception as e:
                print(f"[weekly] Error {uid}: {e}")

    await asyncio.gather(*[safe_build(u) for u in users])
    print(f"[weekly] Done: {week_id}")

if __name__ == "__main__":
    asyncio.run(run_weekly_archive())
