"""
月度歸檔排程
每月 1 日凌晨 3 點（台灣時間）執行

功能：
1. 掃描上個月有對話的所有用戶
2. AI 生成月度情緒摘要 + 統計
3. 摘要存入 DB（archives 表）
4. 摘要放入 Redis 等待用戶下次登入領取
5. 刪除原始 session_messages（減少 DB 體積）

Railway Cron 設定：
  Schedule: 0 19 1 * *   （UTC 19:00 = 台灣 03:00，每月 1 日）

手動觸發：
  python archive_scheduler.py
"""

import os
import json
import asyncio
from datetime import datetime, date

import httpx

from services.db_persistent import (
    get_users_with_old_data,
    get_messages_by_month,
    delete_messages_by_month,
    save_archive,
)
from services.redis_client import put_archive

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"


# ── AI 摘要生成 ───────────────────────────────────────────

async def generate_summary(
    messages: list[dict], year_month: str
) -> tuple[str, dict]:
    """
    回傳 (summary_text, stats_dict)
    """
    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    dialogue_sample = "\n".join(user_msgs[:60])

    prompt = f"""以下是用戶在 {year_month} 的心事日記對話紀錄（僅用戶訊息）：

{dialogue_sample}

請以繁體中文回覆，僅輸出 JSON：
{{
  "summary": "三到五句話的月度情緒摘要，溫暖且中性的語氣",
  "themes": ["本月主要困擾主題，最多3個"],
  "growth_note": "一句話觀察用戶這個月的成長或轉變",
  "stats": {{
    "total_turns": {len(messages)},
    "user_message_count": {len(user_msgs)},
    "estimated_avg_mood": "low/medium/high"
  }}
}}"""

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            ANTHROPIC_API,
            headers={
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 800,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"]

    clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    data = json.loads(clean)

    summary = data.get("summary", "")
    stats = {
        "themes": data.get("themes", []),
        "growth_note": data.get("growth_note", ""),
        **data.get("stats", {}),
    }
    return summary, stats


# ── 單一用戶歸檔 ──────────────────────────────────────────

async def archive_user_month(user_id: str, year: int, month: int) -> None:
    year_month = f"{year}-{month:02d}"
    messages = await get_messages_by_month(user_id, year, month)
    if not messages:
        return

    try:
        summary, stats = await generate_summary(messages, year_month)
    except Exception as e:
        print(f"[archive] AI summary failed for {user_id} {year_month}: {e}")
        summary = "本月對話摘要生成失敗，統計資料已保留。"
        stats = {"total_turns": len(messages), "error": str(e)}

    archive_obj = {
        "user_id": user_id,
        "year_month": year_month,
        "summary": summary,
        "stats": stats,
        "raw_count": len(messages),
        "archived_at": datetime.utcnow().isoformat(),
    }

    await save_archive(user_id, year_month, summary, stats, len(messages))

    try:
        await put_archive(user_id, year_month, archive_obj)
    except Exception as e:
        print(f"[archive] Redis put failed for {user_id}: {e}")

    deleted = await delete_messages_by_month(user_id, year, month)
    print(f"[archive] {user_id} {year_month}: {deleted} messages archived")


# ── 全量排程入口 ──────────────────────────────────────────

async def run_monthly_archive() -> None:
    today = date.today()
    if today.month == 1:
        year, month = today.year - 1, 12
    else:
        year, month = today.year, today.month - 1

    print(f"[archive] Starting for {year}-{month:02d}")
    users = await get_users_with_old_data(year, month)
    print(f"[archive] {len(users)} users to archive")

    sem = asyncio.Semaphore(5)

    async def safe_archive(uid: str):
        async with sem:
            try:
                await archive_user_month(uid, year, month)
            except Exception as e:
                print(f"[archive] Error for {uid}: {e}")

    await asyncio.gather(*[safe_archive(u) for u in users])
    print(f"[archive] Completed for {year}-{month:02d}")


if __name__ == "__main__":
    asyncio.run(run_monthly_archive())
