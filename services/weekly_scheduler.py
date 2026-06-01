"""
週報排程
- 每週一凌晨 3 點執行（處理上週 Mon-Sun）
- AI 生成摘要 + 情緒統計 + 主題
- 組成 WeeklyReport → Redis 待領
- 刪除 MariaDB 原始資料
"""
import json, asyncio
from datetime import datetime, date, timedelta
from typing import Optional

try:
    import aiomysql
except ImportError:
    aiomysql = None

from services.db_persistent import get_pool
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

# ── DB 查詢 ───────────────────────────────────────────────
async def get_users_in_range(start: date, end: date) -> list[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT DISTINCT user_id FROM session_messages "
                "WHERE DATE(created_at) BETWEEN %s AND %s",
                (start, end),
            )
            return [r[0] for r in await cur.fetchall()]

async def get_messages_in_range(user_id: str, start: date, end: date) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT role, content, created_at FROM session_messages "
                "WHERE user_id=%s AND DATE(created_at) BETWEEN %s AND %s "
                "ORDER BY created_at",
                (user_id, start, end),
            )
            rows = await cur.fetchall()
            # datetime → isoformat
            for r in rows:
                if isinstance(r.get("created_at"), datetime):
                    r["created_at"] = r["created_at"].isoformat()
            return rows

async def get_psych_in_range(user_id: str, start: date, end: date) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT arousal, emotion, cognition, created_at "
                "FROM session_psych "
                "WHERE user_id=%s AND DATE(created_at) BETWEEN %s AND %s "
                "ORDER BY created_at",
                (user_id, start, end),
            )
            rows = await cur.fetchall()
            for r in rows:
                if isinstance(r.get("created_at"), datetime):
                    r["created_at"] = r["created_at"].isoformat()
            return rows

async def delete_messages_in_range(user_id: str, start: date, end: date) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM session_messages "
                "WHERE user_id=%s AND DATE(created_at) BETWEEN %s AND %s",
                (user_id, start, end),
            )
            return cur.rowcount

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
async def build_weekly_report(
    user_id: str, start: date, end: date, week_id: str
) -> Optional[dict]:
    messages   = await get_messages_in_range(user_id, start, end)
    psych_rows = await get_psych_in_range(user_id, start, end)

    if not messages:
        return None

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

    report = {
        "week_id":     week_id,
        "user_id":     user_id,
        "start":       start.isoformat(),
        "end":         end.isoformat(),
        "summary":     summary,
        "themes":      themes,
        "growth_note": growth_note,
        "stats":       stats,
        "raw_count":   len(messages),
        "created_at":  datetime.utcnow().isoformat(),
    }

    # 存 Redis 等待用戶領取
    await put_weekly_report(user_id, week_id, report)

    # 刪除原始資料
    deleted = await delete_messages_in_range(user_id, start, end)
    print(f"[weekly] {user_id} {week_id}: {deleted} msgs deleted, report queued")

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
