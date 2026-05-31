import os
import json
import httpx

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"


def _get_headers() -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    return {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }


async def analyze_message(text: str) -> dict:
    """分析用戶訊息，回傳情緒標籤與建議方法"""

    prompt = f"""你是一個心理健康對話分析系統。
分析以下用戶訊息，回傳 JSON 標籤，不要任何其他文字。

用戶訊息：「{text}」

回傳格式：
{{
  "emotion": "ACUTE_DISTRESS|RUMINATION|SELF_BLAME|CONFUSION|CALM_REFLECTIVE",
  "cognition": "FIXED_BELIEF|CATASTROPHIZING|LOGICAL_READY|INSIGHT_EMERGING",
  "need": "NEED_RELEASE|NEED_STRUCTURE|NEED_CHALLENGE|NEED_DISCOVERY",
  "confidence": 0.0到1.0之間的數字,
  "core_belief": "提取用戶的核心負面信念，沒有則填null",
  "suggested_method": "SQT|METACOGNITION|BYRON_KATIE|SOCRATIC"
}}

選擇 suggested_method 的規則：
- ACUTE_DISTRESS 或 RUMINATION → SQT
- FIXED_BELIEF 或 CATASTROPHIZING → BYRON_KATIE
- LOGICAL_READY → METACOGNITION
- INSIGHT_EMERGING → SOCRATIC"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                API_URL,
                headers=_get_headers(),
                json={
                    "model": MODEL,
                    "max_tokens": 500,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            data = response.json()
            if "content" not in data:
                print(f"[AI Label Error] API response: {data}")
                raise ValueError(f"Unexpected API response: {data}")
            text_result = data["content"][0]["text"].strip()
            text_result = text_result.replace("```json", "").replace("```", "").strip()
            return json.loads(text_result)

    except Exception as e:
        print(f"[AI Label Error] {e}")
        return {
            "emotion": "CONFUSION",
            "cognition": "LOGICAL_READY",
            "need": "NEED_RELEASE",
            "confidence": 0.5,
            "core_belief": None,
            "suggested_method": "BYRON_KATIE"
        }


async def analyze_checkin(text: str, known_emotion: str) -> dict:
    """分析簽到自由輸入，補充認知與需求標籤"""

    prompt = f"""用戶今日簽到，已選情緒：{known_emotion}
用戶補充說：「{text}」

請分析並回傳 JSON，不要任何其他文字：
{{
  "cognition": "FIXED_BELIEF|CATASTROPHIZING|LOGICAL_READY|INSIGHT_EMERGING",
  "need": "NEED_RELEASE|NEED_STRUCTURE|NEED_CHALLENGE|NEED_DISCOVERY",
  "reflection": "一句15字內的溫暖回應，不給建議，只是讓用戶感到被理解"
}}"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                API_URL,
                headers=_get_headers(),
                json={
                    "model": MODEL,
                    "max_tokens": 300,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            data = response.json()
            if "content" not in data:
                print(f"[Checkin AI Error] API response: {data}")
                raise ValueError(f"Unexpected API response: {data}")
            text_result = data["content"][0]["text"].strip()
            text_result = text_result.replace("```json", "").replace("```", "").strip()
            return json.loads(text_result)

    except Exception as e:
        print(f"[Checkin AI Error] {e}")
        return {
            "cognition": "LOGICAL_READY",
            "need": "NEED_RELEASE",
            "reflection": "謝謝你願意說出來，這需要勇氣。"
        }
