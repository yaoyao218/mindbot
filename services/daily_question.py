"""
P0-A 今日一問推播系統
- AI 每日生成一個問題並推播到 LINE
- 用戶可自訂推播時間
- 記錄近期使用過的題目（避免重複）
"""

import os
import json
import asyncio
from datetime import datetime, date, timedelta
from typing import Optional

from services.llm import call_api

# ── 每日一問 Prompt ────────────────────────────────────────

DAILY_QUESTION_SYSTEM_PROMPT = """你是心事日記，現在要生成今天的「今日一問」。

生成規則：
- 一個問題，不超過 3 行
- 問的是「今天的一個瞬間或感受」，不是抽象的人生提問
- 語氣輕，像邀請，不像作業
- 不重複近期已使用過的題目

輸出格式（只輸出這個，不要其他文字）：
🌙 今晚的一個問題——
[問題內容]
（想到什麼就說，不用完整）"""

FALLBACK_QUESTIONS = [
    "🌙 今晚的一個問題——\n今天有沒有哪一刻，讓你停了一下？\n（想到什麼就說，不用完整）",
    "🌙 今晚的一個問題——\n今天你用了最多力氣在哪件事上？\n（想到什麼就說，不用完整）",
    "🌙 今晚的一個問題——\n今天有沒有什麼，是你本來不想說但說出來了的？\n（想到什麼就說，不用完整）",
    "🌙 今晚的一個問題——\n今天哪一刻你覺得身體最緊或最鬆？\n（想到什麼就說，不用完整）",
    "🌙 今晚的一個問題——\n如果今天的情緒要用一個天氣來形容，你會選什麼？\n（想到什麼就說，不用完整）",
    "🌙 今晚的一個問題——\n今天有沒有什麼讓你覺得「還好」的小事？\n（想到什麼就說，不用完整）",
    "🌙 今晚的一個問題——\n今天你對自己說了什麼話？\n（想到什麼就說，不用完整）",
]


async def generate_daily_question(recent_questions: list[str]) -> str:
    """AI 生成今日一問，帶近期題目上下文避免重複"""
    recent_str = "\n".join(f"- {q}" for q in recent_questions[-7:]) if recent_questions else "（無）"
    prompt = (
        f"近期已使用過的題目：\n{recent_str}\n\n"
        f"請生成今天的「今日一問」，不要和上面重複。\n"
        f"只輸出問題訊息本身，格式如下：\n"
        f"🌙 今晚的一個問題——\n[問題內容]\n（想到什麼就說，不用完整）"
    )
    try:
        result = await call_api(
            prompt=prompt,
            system=DAILY_QUESTION_SYSTEM_PROMPT,
            max_tokens=120,
        )
        if result and "🌙" in result:
            return result.strip()
    except Exception as e:
        print(f"[DailyQ] AI generation failed: {e}")

    # Fallback：靜態題庫隨機選一個非近期的
    used = set(recent_questions)
    available = [q for q in FALLBACK_QUESTIONS if q not in used]
    if not available:
        available = FALLBACK_QUESTIONS
    import random
    return random.choice(available)


# ── DB 操作（依賴 db_persistent）──────────────────────────

async def get_recent_questions(user_id: str, days: int = 14) -> list[str]:
    """取得近 N 天內已推播過的題目"""
    try:
        from services.db_persistent import get_pool
        pool = await get_pool()
        cutoff = date.today() - timedelta(days=days)
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT question_text FROM daily_questions
                    WHERE user_id = %s AND sent_date >= %s
                    ORDER BY sent_date DESC
                    """,
                    (user_id, cutoff)
                )
                rows = await cur.fetchall()
                return [r[0] for r in rows]
    except Exception:
        return []


async def save_daily_question(user_id: str, question_text: str) -> None:
    """記錄已推播的題目"""
    try:
        from services.db_persistent import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO daily_questions (user_id, question_text, sent_date)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE question_text = VALUES(question_text)
                    """,
                    (user_id, question_text, date.today())
                )
    except Exception as e:
        print(f"[DailyQ] save failed: {e}")


async def get_push_schedule(user_id: str) -> Optional[dict]:
    """取得用戶的推播時間設定"""
    try:
        from services.db_persistent import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT push_hour, push_minute, enabled FROM push_schedule WHERE user_id = %s",
                    (user_id,)
                )
                row = await cur.fetchone()
                if row:
                    return {"hour": row[0], "minute": row[1], "enabled": bool(row[2])}
    except Exception:
        pass
    return None


async def set_push_schedule(user_id: str, hour: int, minute: int) -> None:
    """設定用戶的推播時間"""
    try:
        from services.db_persistent import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO push_schedule (user_id, push_hour, push_minute, enabled)
                    VALUES (%s, %s, %s, 1)
                    ON DUPLICATE KEY UPDATE
                        push_hour = VALUES(push_hour),
                        push_minute = VALUES(push_minute),
                        enabled = 1
                    """,
                    (user_id, hour, minute)
                )
    except Exception as e:
        print(f"[DailyQ] set_push_schedule failed: {e}")


async def get_all_push_users() -> list[dict]:
    """取得所有啟用推播的用戶及其時間"""
    try:
        from services.db_persistent import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT user_id, push_hour, push_minute FROM push_schedule WHERE enabled = 1"
                )
                rows = await cur.fetchall()
                return [{"user_id": r[0], "hour": r[1], "minute": r[2]} for r in rows]
    except Exception:
        return []


# ── 推播執行 ────────────────────────────────────────────────

def _build_context_flex(question: str) -> dict:
    """
    每日推播 Flex：今日一問 + 情境選擇（深度 / 快速）
    """
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "backgroundColor": "#0f1410",
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "text",
                    "text": "🌙 今日一問",
                    "size": "xs",
                    "color": "#4a7c59",
                    "weight": "bold",
                    "letterSpacing": "4px",
                },
                {
                    "type": "text",
                    "text": question,
                    "size": "sm",
                    "color": "#e8e0d0",
                    "wrap": True,
                    "lineSpacing": "6px",
                    "margin": "md",
                },
                {
                    "type": "separator",
                    "color": "#ffffff0d",
                    "margin": "lg",
                },
                {
                    "type": "text",
                    "text": "今天想怎麼說？",
                    "size": "xs",
                    "color": "#6b5d4f",
                    "margin": "md",
                },
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "backgroundColor": "#0f1410",
            "paddingAll": "12px",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "postback",
                        "label": "🌙 睡前安靜聊聊",
                        "data": "action=set_context&value=deep",
                        "displayText": "我想睡前安靜聊聊",
                    },
                    "style": "primary",
                    "color": "#4a7c59",
                    "height": "sm",
                },
                {
                    "type": "button",
                    "action": {
                        "type": "postback",
                        "label": "🏃 通勤打卡碎碎念",
                        "data": "action=set_context&value=quick",
                        "displayText": "我想快速打卡碎碎念",
                    },
                    "style": "secondary",
                    "height": "sm",
                },
            ],
        },
    }


async def send_daily_question_to_user(user_id: str, line_bot_api) -> bool:
    """對單一用戶生成並推播今日一問（附情境選擇 Flex）"""
    try:
        from linebot.v3.messaging import (
            PushMessageRequest, FlexMessage, FlexContainer
        )

        # 取得近期題目 + AI 生成
        recent   = await get_recent_questions(user_id)
        question = await generate_daily_question(recent)

        # 推播：情境選擇 Flex（取代純文字）
        await line_bot_api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=[FlexMessage(
                    alt_text=question,
                    contents=FlexContainer.from_dict(_build_context_flex(question))
                )]
            )
        )

        # 記錄
        await save_daily_question(user_id, question)
        print(f"[DailyQ] Sent to {user_id[:8]}…")
        return True
    except Exception as e:
        print(f"[DailyQ] Failed for {user_id[:8]}…: {e}")
        return False


async def run_daily_question_scheduler(line_bot_api) -> None:
    """
    每分鐘檢查是否有用戶的推播時間到了
    由 APScheduler 每分鐘呼叫一次
    """
    import pytz
    tz = pytz.timezone("Asia/Taipei")
    now = datetime.now(tz)
    current_hour = now.hour
    current_minute = now.minute

    users = await get_all_push_users()
    tasks = []
    for u in users:
        if u["hour"] == current_hour and u["minute"] == current_minute:
            tasks.append(send_daily_question_to_user(u["user_id"], line_bot_api))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
        print(f"[DailyQ] Processed {len(tasks)} users at {current_hour:02d}:{current_minute:02d}")


# ── 推播時間設定解析 ─────────────────────────────────────────

def parse_push_time(text: str) -> Optional[tuple[int, int]]:
    """
    解析用戶輸入的推播時間，支援格式：
    - "21:00", "晚上9點", "9點", "九點"
    返回 (hour, minute) 或 None
    """
    import re
    # HH:MM 格式
    m = re.search(r"(\d{1,2}):(\d{2})", text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h < 24 and 0 <= mi < 60:
            return h, mi

    # "X點" 格式
    m = re.search(r"(\d{1,2})\s*[點点]", text)
    if m:
        h = int(m.group(1))
        if "下午" in text or "晚上" in text or "傍晚" in text:
            if h < 12:
                h += 12
        if 0 <= h < 24:
            return h, 0

    return None


PUSH_SETUP_KEYWORDS = ["設定推播", "推播時間", "每天提醒", "提醒我", "每天問我"]
PUSH_CANCEL_KEYWORDS = ["關閉推播", "取消推播", "不要推播", "停止推播"]
