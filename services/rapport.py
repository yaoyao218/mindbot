"""
關係建立模組（前兩輪）
第一輪：純傾聽，不分析不提問
第二輪：繼續傾聽 + 輕詢今天想要什麼
"""

import os
import json
import httpx

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"


def _get_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "anthropic-version": "2023-06-01",
    }


async def rapport_turn_1(user_text: str) -> str:
    """
    第一輪：純傾聽回應
    不分析、不提問、不給建議
    讓用戶感到被聽見
    """
    prompt = f"""你是一個溫暖的傾聽者。用戶說了：「{user_text}」

請給出一個純傾聽的回應（30-60字）：
- 不分析、不提問、不給建議
- 讓用戶感到被聽見、被接納
- 用第一人稱，像朋友在說話
- 不用任何標題或分段

只回傳回應文字，不要任何其他內容。"""

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                API_URL,
                headers=_get_headers(),
                json={
                    "model": MODEL,
                    "max_tokens": 150,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            data = response.json()
            return data["content"][0]["text"].strip()
    except Exception as e:
        print(f"[Rapport Turn 1 Error] {e}")
        return "謝謝你願意說出這些。聽起來你心裡有很多東西。"


async def rapport_turn_2(user_text: str, turn_1_text: str) -> str:
    """
    第二輪：繼續傾聽 + 輕詢今天想要什麼
    一個輕柔的開放式問題
    """
    prompt = f"""你是一個溫暖的傾聽者。對話進行到第二輪。

用戶之前說：「{turn_1_text}」
你上一輪回應了（傾聽回應）。
用戶現在說：「{user_text}」

請給出回應（40-70字）：
- 先繼續傾聽，讓用戶感到被接納
- 最後加一個輕柔的問句：今天來這裡，最想要的是什麼？
  （可以是想說出來、想理清楚、還是只是想有人陪）
- 語氣溫和，不急迫

只回傳回應文字，不要任何其他內容。"""

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                API_URL,
                headers=_get_headers(),
                json={
                    "model": MODEL,
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            data = response.json()
            return data["content"][0]["text"].strip()
    except Exception as e:
        print(f"[Rapport Turn 2 Error] {e}")
        return "我在這裡，繼續聽你說。今天來這裡，最想要的是什麼呢？"
