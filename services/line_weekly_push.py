"""
P2-B LINE 週報摘要推播
在週報生成完成後，將精簡版週報直接 push 到 LINE
"""

import asyncio
from datetime import date, timedelta
from typing import Optional

from services.llm import call_api


WEEKLY_PUSH_OBSERVATION_PROMPT = """以下是用戶本週的數據摘要：
對話天數：{days}
情緒序列：{emoji_sequence}
高頻關鍵詞：{keywords}

請生成一句讓用戶感覺「這週被看見了」的觀察。

規則：
- 不超過兩句
- 說趨勢或模式，不說評價
- 不給建議
- 語氣輕，不是報告，是朋友說的一句話
只輸出觀察文字。"""


async def generate_push_observation(
    days: int,
    emoji_sequence: str,
    keywords: list[str],
) -> str:
    kw_str = "、".join(keywords[:3]) if keywords else "（暫無）"
    try:
        result = await call_api(
            prompt="請生成觀察文字。",
            system=WEEKLY_PUSH_OBSERVATION_PROMPT.format(
                days=days,
                emoji_sequence=emoji_sequence,
                keywords=kw_str,
            ),
            max_tokens=80,
        )
        return result.strip() if result else ""
    except Exception:
        return ""


def format_weekly_push_message(
    days: int,
    emojis: str,
    keywords: list[str],
    observation: str,
) -> str:
    kw_display = "　".join(f"「{k}」" for k in keywords[:3]) if keywords else ""
    lines = [
        "🌙 本週的你——",
        f"對話了 {days} 天",
        f"這週的情緒：{emojis}",
    ]
    if kw_display:
        lines.append(f"最常出現的主題：\n{kw_display}")
    if observation:
        lines.append(f"\n{observation}")
    return "\n".join(lines)


async def push_weekly_reports_to_line(line_bot_api) -> None:
    """
    將本週報告推播給所有有訂閱的用戶
    在週報生成完（run_weekly_archive）後約 5 分鐘執行
    """
    try:
        from services.weekly_scheduler import get_last_week_range
        from services.db_persistent import get_pool, get_emotion_calendar, get_top_keywords
        from linebot.v3.messaging import PushMessageRequest, TextMessage, FlexMessage, FlexContainer

        start, end, week_id = get_last_week_range()

        pool = await get_pool()

        # 取得有週報的用戶
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT user_id, summary, stats FROM archives WHERE year_month = %s",
                    (week_id,)
                )
                rows = await cur.fetchall()

        if not rows:
            print("[WeeklyPush] No reports found for", week_id)
            return

        import json as _json
        sem = asyncio.Semaphore(3)

        async def push_one(user_id: str, summary: str, stats_raw: str):
            async with sem:
                try:
                    import ast
                    stats = _json.loads(stats_raw) if isinstance(stats_raw, str) else (stats_raw or {})
                    days = stats.get("user_msg_count", 0)

                    # 取得情緒 emoji 序列
                    today = date.today()
                    cal_records = await get_emotion_calendar(
                        user_id, start.year, start.month
                    )
                    emojis = "".join(r.get("emotion_emoji", "😐") for r in cal_records[-7:]) or "🌙"

                    # 取得關鍵詞
                    keywords = await get_top_keywords(user_id, limit=3)

                    # AI 生成觀察
                    observation = await generate_push_observation(days, emojis, keywords)

                    msg_text = format_weekly_push_message(days, emojis, keywords, observation)

                    from handlers.message import _website_flex, APP_URL
                    await line_bot_api.push_message(
                        PushMessageRequest(
                            to=user_id,
                            messages=[
                                TextMessage(text=msg_text),
                                _website_flex(),
                            ]
                        )
                    )
                    print(f"[WeeklyPush] Sent to {user_id[:8]}…")
                except Exception as e:
                    print(f"[WeeklyPush] Error for {user_id[:8]}…: {e}")

        await asyncio.gather(*[push_one(r[0], r[1], r[2]) for r in rows])
        print(f"[WeeklyPush] Done: {week_id}")

    except Exception as e:
        print(f"[WeeklyPush] Fatal: {e}")
