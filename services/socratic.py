"""
蘇格拉底式對話模組（非線性）
Phase 0: 洞察就緒評估（LOW/MEDIUM/HIGH）
Phase 1: 動態六策略選擇器（最多 6 輪）
頓悟偵測：自動收束
Padesky 四要素貫穿全程
"""

import os
import json
import httpx

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"

STRATEGIES = [
    "concretize",        # 拉到具體事件
    "counter_example",   # 帶入例外
    "perspective_shift", # 換位思考
    "pattern_recognition",# 看見重複模式
    "standard_check",    # 對自己 vs 對別人的標準
    "open_discovery",    # 讓用戶自己說出結論
]


def _get_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "anthropic-version": "2023-06-01",
    }


async def _call_api(prompt: str, max_tokens: int = 300, model: str = MODEL) -> str:
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                API_URL, headers=_get_headers(),
                json={"model": model, "max_tokens": max_tokens,
                      "messages": [{"role": "user", "content": prompt}]}
            )
            return response.json()["content"][0]["text"].strip()
    except Exception as e:
        print(f"[Socratic API Error] {e}")
        return ""


async def assess_insight_readiness(user_text: str) -> dict:
    """
    Phase 0：評估洞察就緒程度
    回傳 {"readiness": "LOW|MEDIUM|HIGH", "depth": "surface|moderate|deep"}
    """
    prompt = f"""評估用戶的洞察就緒程度。只回傳 JSON。

用戶訊息：「{user_text}」

- HIGH：用戶已有明確的自我質疑，主動想理解模式（「我好像每次都...」「我不知道為什麼我總是...」）
- MEDIUM：用戶有模糊的自我覺察，但還不確定（「也許是我的問題？」）
- LOW：用戶還在陳述事實，尚未開始自我質疑

回傳：{{"readiness": "LOW|MEDIUM|HIGH", "depth": "surface|moderate|deep"}}"""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                API_URL, headers=_get_headers(),
                json={"model": "claude-haiku-4-5-20251001", "max_tokens": 100,
                      "messages": [{"role": "user", "content": prompt}]}
            )
            text = response.json()["content"][0]["text"].strip()
            text = text.replace("```json", "").replace("```", "").strip()
            return json.loads(text)
    except Exception:
        return {"readiness": "MEDIUM", "depth": "moderate"}


async def choose_strategy(
    user_text: str,
    history: list[dict],
    used_strategies: list[str],
    readiness: str
) -> str:
    """選擇最適合的下一個蘇格拉底策略"""
    available = [s for s in STRATEGIES if s not in used_strategies]
    if not available:
        return "open_discovery"

    history_text = "\n".join([
        f"{'用戶' if h['role'] == 'user' else 'Bot'}: {h['text']}"
        for h in history[-4:]
    ])

    prompt = f"""選擇最適合的蘇格拉底策略。只回傳策略名稱，不要其他文字。

對話記錄：
{history_text}

用戶最新說：「{user_text}」
洞察就緒程度：{readiness}
可用策略：{available}

策略說明：
- concretize：拉到一個具體事件（當用戶說法太抽象）
- counter_example：帶入例外情況（打破絕對化思考）
- perspective_shift：換位思考（問如果是朋友，你會怎麼說）
- pattern_recognition：看見跨情境的重複模式
- standard_check：比較對自己和對別人的不同標準
- open_discovery：讓用戶自己說出結論（適合接近頓悟時）

只回傳策略名稱（如：concretize）"""

    result = await _call_api(prompt, max_tokens=30, model="claude-haiku-4-5-20251001")
    result = result.strip().lower()
    return result if result in STRATEGIES else (available[0] if available else "open_discovery")


async def detect_insight(user_text: str) -> bool:
    """偵測用戶是否出現頓悟或洞察"""
    insight_markers = [
        "原來", "我發現", "所以其實", "也就是說", "我明白了",
        "怪不得", "難怪", "我好像懂了", "這讓我想到", "我從來沒這樣想過"
    ]
    # 快速關鍵字檢查
    if any(m in user_text for m in insight_markers):
        return True
    return False


STRATEGY_PROMPTS = {
    "concretize": "請用蘇格拉底方式把對話拉到一個具體的事件：問用戶能不能說一個最近發生的具體例子。",
    "counter_example": "請用蘇格拉底方式帶入例外：問用戶有沒有哪次情況不是這樣的，那次有什麼不同。",
    "perspective_shift": "請用蘇格拉底方式引導換位思考：問如果是用戶最在乎的朋友遇到一樣的情況，用戶會怎麼看待他/她。",
    "pattern_recognition": "請用蘇格拉底方式引導看見模式：問用戶這個感受或情況在生活的其他地方有沒有也出現過。",
    "standard_check": "請用蘇格拉底方式引導標準檢查：問用戶如果別人也這樣做，用戶會對他們這麼嚴格嗎？為什麼對自己不一樣？",
    "open_discovery": "請用蘇格拉底方式讓用戶自己得出結論：問用戶根據剛才說的這些，他們覺得這代表什麼？",
}


async def get_reply(session: dict, user_text: str) -> tuple[str, dict]:
    """主入口"""
    phase = session.get("phase", 0)
    readiness_info = session.get("readiness_info", {})
    readiness = readiness_info.get("readiness", "MEDIUM")
    depth = readiness_info.get("depth", "moderate")
    used_strategies = session.get("used_strategies", [])
    socratic_turn = session.get("socratic_turn", 0)
    history = session.get("history", [])
    updates = {}

    # ── Phase 0：洞察就緒評估 ──────────────────────────────
    if phase == 0:
        info = await assess_insight_readiness(user_text)
        readiness = info["readiness"]
        updates["readiness_info"] = info
        updates["phase"] = 1
        updates["socratic_turn"] = 0
        updates["used_strategies"] = []

        # 第一個策略：依就緒程度選
        first_strategy = "concretize" if readiness == "LOW" else \
                         "counter_example" if readiness == "MEDIUM" else \
                         "perspective_shift"
        updates["used_strategies"] = [first_strategy]
        updates["socratic_turn"] = 1

        prompt = f"""你是蘇格拉底式對話的引導者。用戶說：「{user_text}」
洞察就緒：{readiness}

{STRATEGY_PROMPTS[first_strategy]}

Padesky 四要素：
a. 只問用戶本身有知識能回答的問題
b. 帶入用戶目前焦點外的角度
c. 從具體到抽象
d. 不給答案，讓用戶自己得出結論

給出 40-60 字的回應，只回傳對話文字。"""
        reply = await _call_api(prompt)
        return reply or "能說一個最近具體發生的例子嗎？", updates

    # ── Phase 1：動態策略對話（最多 6 輪）─────────────────
    if phase == 1:
        # 頓悟偵測
        if await detect_insight(user_text) or socratic_turn >= 6:
            updates["phase"] = 2
            prompt = f"""用戶在蘇格拉底對話後說：「{user_text}」
這可能是頓悟或洞察的時刻。

請給出收束性的溫暖回應（40-60字）：
- 反映用戶剛才說的洞察
- 輕輕問：「這個發現，對你來說意味著什麼？」
只回傳對話文字。"""
            reply = await _call_api(prompt)
            return reply or "你剛才說的讓我很有感。這個發現，對你來說意味著什麼？", updates

        # 選下一個策略
        strategy = await choose_strategy(user_text, history, used_strategies, readiness)
        used_strategies.append(strategy)
        updates["used_strategies"] = used_strategies
        updates["socratic_turn"] = socratic_turn + 1

        prompt = f"""你是蘇格拉底式對話的引導者。

最近對話：
{chr(10).join([f"{'用戶' if h['role'] == 'user' else 'Bot'}: {h['text']}" for h in history[-4:]])}

用戶說：「{user_text}」
選定策略：{strategy}

{STRATEGY_PROMPTS[strategy]}

Padesky 四要素：不給答案，讓用戶自己得出結論。
給出 40-60 字的回應，只回傳對話文字。"""
        reply = await _call_api(prompt)
        return reply or "這讓我好奇：有沒有哪次不一樣的情況？", updates

    # ── Phase 2：結語 ──────────────────────────────────────
    return "謝謝你今天願意這樣深入地看自己。你的洞察，是你自己找到的。", {}
