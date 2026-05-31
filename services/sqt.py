"""
SQT 自我提問療法對話模組
Step 0: 邀請說出念頭（純傾聽）
Step 1: 語言解融
Step 2: 語言 + 身體雙軌覺察
Step 3: 手掌比喻，觀察而不追隨
Step 4: 念頭可信度再評估（D-FUSE）
"""

import os
import httpx

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"


def _get_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "anthropic-version": "2023-06-01",
    }


async def _call_api(prompt: str, max_tokens: int = 300) -> str:
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                API_URL, headers=_get_headers(),
                json={"model": MODEL, "max_tokens": max_tokens,
                      "messages": [{"role": "user", "content": prompt}]}
            )
            return response.json()["content"][0]["text"].strip()
    except Exception as e:
        print(f"[SQT API Error] {e}")
        return ""


async def get_reply(session: dict, user_text: str) -> tuple[str, dict]:
    """
    主入口：依 session step 回傳下一步
    回傳 (reply_text, updated_session_fields)
    """
    step = session.get("step", 0)
    updates = {}

    if step == 0:
        # 純傾聽，邀請說出主要念頭
        updates["step"] = 1
        prompt = f"""用戶說：「{user_text}」
情緒狀態：急性痛苦或反芻思考

請給出 SQT Step 0 的回應（40-60字）：
- 純傾聽，讓用戶感到被聽見
- 最後問：「現在腦袋裡最大聲的那個念頭是什麼？」
不要分析、不要建議。只回傳對話文字。"""
        reply = await _call_api(prompt)
        return reply or "聽起來你腦袋裡有很多在轉。現在最大聲的那個念頭是什麼？", updates

    if step == 1:
        # 語言解融
        thought = user_text
        updates["step"] = 2
        updates["main_thought"] = thought
        reply = (
            f"好，我聽到了。\n\n"
            f"現在試試看，在心裡說：\n\n"
            f"「**我現在有一個念頭，它說：{thought}**」\n\n"
            f"說完了嗎？說說看，加了這句話之後感覺有什麼不一樣？"
        )
        return reply, updates

    if step == 2:
        # 語言 + 身體雙軌覺察
        updates["step"] = 3
        prompt = f"""用戶剛完成了 SQT 語言解融練習。
用戶回應：「{user_text}」

請給出 Step 2 雙軌覺察引導（50-70字）：
- 先承接用戶的感受
- 問兩件事：
  1. 如果要給這個念頭的「可信度」打分，0是完全不信，10是完全相信，現在幾分？
  2. 這個念頭在你身體的哪個位置？胸口、喉嚨、還是其他地方？
只回傳對話文字。"""
        reply = await _call_api(prompt)
        return reply or "謝謝你說的。如果要給這個念頭的可信度打分，0到10，你現在給幾分？\n\n同時，這個念頭在你身體的哪個位置？", updates

    if step == 3:
        # 手掌比喻
        updates["step"] = 4
        reply = (
            "謝謝你注意到這些。\n\n"
            "現在我想邀請你做一個小練習：\n\n"
            "想像你的念頭寫在你的手掌上。\n"
            "你可以看著它，但不需要把手掌貼在臉上——\n"
            "也不需要把手甩開。\n\n"
            "就讓它在那裡，你繼續走你的路。\n\n"
            "你能感覺到這個距離嗎？"
        )
        return reply, updates

    if step == 4:
        # D-FUSE 念頭可信度再評估
        updates["step"] = 5
        prompt = f"""用戶完成了 SQT 手掌比喻練習。
用戶回應：「{user_text}」

請給出 Step 4 D-FUSE 再評估引導（50-70字）：
- 先承接用戶的體驗
- 詢問：「現在再給這個念頭的可信度打一次分，和剛才比起來，有沒有什麼變化？」
- 說明：不管分數有沒有變，都沒有對錯
只回傳對話文字。"""
        reply = await _call_api(prompt)
        return reply or "謝謝你走到這裡。現在再給這個念頭的可信度打一次分，和剛才比，有什麼變化嗎？", updates

    if step == 5:
        # 結尾
        updates["step"] = 6
        prompt = f"""用戶完成了 SQT 五步練習。
用戶最後回應：「{user_text}」

請給出溫暖的結語（40-60字）：
- 反映用戶走過的過程
- 讓用戶知道：念頭不一定要消失，能有一點距離就是進展
- 問：「現在身體感覺怎麼樣？」
只回傳對話文字。"""
        reply = await _call_api(prompt)
        return reply or "謝謝你走過這五步。念頭不一定消失，但你和它之間有了一點空間——這就是進展。現在身體感覺怎麼樣？", updates

    # 後續維持對話
    return "你剛才走過的很不容易。如果念頭又來了，記得可以再用這個練習。你現在感覺如何？", {}
