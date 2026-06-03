"""
daily_narrative.py — AI 每日敘述生成與快取

每天的情緒旅程，由 AI 以溫柔的敘述者視角整理成 3–4 句話，
自然帶入塔羅牌的意象，存入 emotion_calendar.daily_narrative。
"""

from datetime import date
from services.llm import call_api
from services.db_persistent import (
    get_daily_record, save_daily_narrative, get_pool,
)


async def _get_today_messages(user_id: str, record_date: date) -> list[str]:
    """取得當天用戶訊息（最多 20 則）"""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT content FROM session_messages
                WHERE user_id=$1 AND role='user'
                  AND created_at::date=$2
                ORDER BY created_at
                LIMIT 20
                """,
                user_id, record_date
            )
        return [r["content"] for r in rows]
    except Exception:
        return []


async def generate_day_narrative(
    user_id: str,
    record_date: date,
    messages: list[str],
    tarot_info: dict,
) -> str:
    """
    用 AI 生成當天的敘述性日記文字。
    tarot_info: assign_tarot_structured() 回傳的 dict
    """
    msg_sample = "\n".join(f"・{m}" for m in messages[:20]) if messages else "（無對話紀錄）"

    if tarot_info and tarot_info.get("card_name"):
        pos = "逆位" if tarot_info.get("is_reversed") else "正位"
        tarot_context = f"今天抽到的牌是【{tarot_info['card_name']}・{pos}】，其意象：「{tarot_info['meaning']}」"
    elif tarot_info and tarot_info.get("mode") == "quote":
        tarot_context = f"今天的情緒名言：「{tarot_info['meaning']}」"
    else:
        tarot_context = ""

    prompt = f"""以下是用戶在 {record_date} 這天說的話：

{msg_sample}

{tarot_context}

請以溫柔的旁觀者視角，用繁體中文寫 3–4 句話的敘述性短文，整理這一天的情緒旅程。
要求：
- 語氣溫暖、不評判
- 自然融入塔羅牌的意象（如果有）
- 不要重複用戶說的每一句話，只提煉核心情感
- 直接輸出文字，不要有任何前言或引號包裹"""

    result = await call_api(prompt, max_tokens=300, tier="haiku")
    return result.strip() if result else ""


async def get_or_generate_narrative(user_id: str, record_date: date) -> dict:
    """
    取得當天完整日記錄。若 daily_narrative 為空，
    自動生成並存入 DB，再回傳。
    """
    record = await get_daily_record(user_id, record_date)

    # 已有敘述，直接回傳
    if record.get("daily_narrative"):
        return record

    # 需要生成
    messages = await _get_today_messages(user_id, record_date)
    if not messages and not record.get("found"):
        return {**record, "daily_narrative": None, "generated": False}

    tarot_info = None
    if record.get("tarot_card"):
        tarot_info = {
            "card_name":   record["tarot_card"],
            "meaning":     record["tarot_meaning"] or "",
            "is_reversed": record.get("tarot_reversed", False),
            "mode":        "major",
        }

    narrative = await generate_day_narrative(user_id, record_date, messages, tarot_info)
    if narrative:
        await save_daily_narrative(user_id, record_date, narrative)
        record["daily_narrative"] = narrative
        record["generated"] = True
    else:
        record["generated"] = False

    return record
