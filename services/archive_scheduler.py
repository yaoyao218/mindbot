"""
月度歸檔排程
- 每月1日凌晨3點觸發（Railway Cron 或 APScheduler）
- 針對上個月的對話：AI 生成摘要 + 統計
- 結果存 DB archives + Redis 等待用戶領取
- 原始 session_messages 刪除
"""
import os, json, asyncio
from datetime import datetime, date
from calendar import monthrange
import httpx

from services.db_persistent import (
    get_users_with_old_data,
    get_messages_by_month,
    delete_messages_by_month,
    save_archive,
    get_pool,
)
from services.redis_client import put_archive

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"

# ── AI 摘要生成 ───────────────────────────────────────────
async def generate_summary(messages: list[dict], year_month: str) -> tuple[str, dict]:
    """
    回傳 (summary_text, stats_dict)
    stats: { total_turns, emotion_counts, top_methods, avg_arousal, mood_trend }
    """
    # 組成對話文字（僅 user 訊息用於摘要）
    user_msgs = [m["content"] for m in messages if m["role"] == "user"]
    dialogue_sample = "\n".join(user_msgs[:60])  # 最多前60則避免超過 context

    prompt = f"""以下是用戶在 {year_month} 的心事日記對話紀錄（僅用戶訊息）：

{dialogue_sample}

請以繁體中文回覆，僅輸出 JSON，格式如下：
{{
  "summary": "三到五句話的月度情緒摘要，溫暖且中性的語氣",
  "themes": ["本月主要困擾主題，最多3個"],
  "growth_note": "一句話觀察用戶這個月的成長或轉變",
  "stats": {{
    "total_turns": {len(messages)},
    "user_message_count": {len(user_msgs)},
    "estimated_avg_mood": "low/medium/high（根據內容估計）"
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

    # 清理 markdown fences
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
        summary = "本月對話摘要生成失敗，原始對話已保留統計資料。"
        stats = {"total_turns": len(messages), "error": str(e)}

    # 組合完整 archive 物件（前端 IndexedDB 直接存這個）
    archive_obj = {
        "user_id": user_id,
        "year_month": year_month,
        "summary": summary,
        "stats": stats,
        "raw_count": len(messages),
        "archived_at": datetime.utcnow().isoformat(),
    }

    # 存 DB（持久備份）
    await save_archive(user_id, year_month, summary, stats, len(messages))

    # 存 Redis（等用戶下次登入來領）
    await put_archive(user_id, year_month, archive_obj)

    # 刪除原始訊息
    deleted = await delete_messages_by_month(user_id, year, month)
    print(f"[archive] {user_id} {year_month}: {deleted} messages archived")


# ── 全量排程入口 ──────────────────────────────────────────
async def run_monthly_archive() -> None:
    """
    每月1日凌晨3點執行，處理上個月所有用戶
    Railway Cron: 0 19 L * * （UTC+0 的 19:00 = 台灣凌晨 3:00）
    """
    today = date.today()
    # 上個月
    if today.month == 1:
        year, month = today.year - 1, 12
    else:
        year, month = today.year, today.month - 1

    print(f"[archive] Starting monthly archive for {year}-{month:02d}")
    users = await get_users_with_old_data(year, month)
    print(f"[archive] Found {len(users)} users to archive")

    # 並發上限 5，避免 AI API 過載
    sem = asyncio.Semaphore(5)

    async def safe_archive(uid: str):
        async with sem:
            try:
                await archive_user_month(uid, year, month)
            except Exception as e:
                print(f"[archive] Error for {uid}: {e}")

    await asyncio.gather(*[safe_archive(u) for u in users])
    print(f"[archive] Completed for {year}-{month:02d}")


# ── 直接執行（手動觸發）────────────────────────────────────
if __name__ == "__main__":
    asyncio.run(run_monthly_archive())
