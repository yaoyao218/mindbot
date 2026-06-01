"""
危機偵測模組（雙層：關鍵字 + AI 確認）
"""

import json
from services.llm import call_api

CRISIS_KEYWORDS = [
    "不想活", "想死", "自殺", "去死", "活不下去",
    "結束生命", "消失算了", "死了算了", "不如死",
    "輕生", "了結", "跳樓", "割腕", "吃藥死"
]

CRISIS_RESPONSE = (
    "我聽到你說的了。\n\n"
    "你現在感受到的痛，是真實的。\n\n"
    "請撥打「安心專線 1925」，24小時都有人陪你說話。\n"
    "你不需要一個人扛這些。"
)


def keyword_check(text: str) -> bool:
    """第一層：關鍵字快篩"""
    return any(kw in text for kw in CRISIS_KEYWORDS)


async def ai_crisis_check(text: str) -> bool:
    """第二層：AI 確認（只在關鍵字命中時呼叫）"""
    prompt = f"""判斷以下訊息是否顯示用戶有立即的自傷或自殺風險。
只回傳 JSON：{{"is_crisis": true}} 或 {{"is_crisis": false}}

訊息：「{text}」"""

    try:
        raw = await call_api(prompt, max_tokens=50, tier="haiku")
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw).get("is_crisis", False)
    except Exception as e:
        print(f"[Crisis AI Error] {e}")
        return True  # 失敗時保守判斷為危機


async def detect_crisis(text: str) -> bool:
    """
    雙層危機偵測
    第一層命中才呼叫 AI；AI 確認後才視為危機
    """
    if keyword_check(text):
        return await ai_crisis_check(text)
    return False


def get_crisis_response() -> str:
    return CRISIS_RESPONSE
