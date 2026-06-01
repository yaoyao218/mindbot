from services.llm import call_api
"""
Byron Katie 四問法對話模組
Phase 0: 認知融合評估
Phase 1: 前置解融（高融合才有）
Phase 2: 四問本體 + 翻轉
Phase 3: 結語
"""



async def assess_fusion(user_text: str, core_belief: str) -> dict:
    """
    Phase 0：評估認知融合程度
    回傳 {"fusion_level": "HIGH"|"LOW", "belief_statement": "..."}
    """
    prompt = f"""評估用戶與以下核心信念的認知融合程度。
只回傳 JSON，不要其他文字。

核心信念：「{core_belief}」
用戶訊息：「{user_text}」

融合程度判斷：
- HIGH：用戶完全認同信念，如「我就是廢人」「我一定做不到」
- LOW：用戶有些距離感，如「我好像不太行」「我覺得自己...」

回傳格式：
{{"fusion_level": "HIGH|LOW", "belief_statement": "用一句話表達核心信念"}}"""

    try:
        raw = await call_api(prompt, max_tokens=150, tier="haiku")
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception:
        return {"fusion_level": "LOW", "belief_statement": core_belief or user_text[:50]}


async def get_reply(session: dict, user_text: str) -> tuple[str, dict]:
    """
    主入口：依 session 狀態回傳下一步回覆
    回傳 (reply_text, updated_session_fields)
    """
    phase = session.get("phase", 0)
    step = session.get("step", 0)
    core_belief = session.get("core_belief", user_text)
    fusion_level = session.get("fusion_level", None)

    updates = {}

    # ── Phase 0：融合評估 ──────────────────────────────────
    if phase == 0:
        result = await assess_fusion(user_text, core_belief)
        fusion_level = result["fusion_level"]
        belief = result["belief_statement"]
        updates["fusion_level"] = fusion_level
        updates["core_belief"] = belief

        if fusion_level == "HIGH":
            updates["phase"] = 1
            updates["step"] = 0
            reply = (
                f"我注意到你說「{belief}」。\n\n"
                "在我們往下探索之前，我想邀請你做一個小練習：\n\n"
                f"試著在心裡說：「我現在有一個念頭，它說：{belief}」\n\n"
                "說完了嗎？說說看你有什麼感覺？"
            )
        else:
            updates["phase"] = 2
            updates["step"] = 1
            reply = (
                f"你說「{belief}」。\n\n"
                "我想問你第一個問題：\n\n"
                "**這是真的嗎？**"
            )
        return reply, updates

    # ── Phase 1：前置解融 ──────────────────────────────────
    if phase == 1:
        belief = core_belief
        if step == 0:
            updates["step"] = 1
            reply = (
                "好。現在再問你一個問題：\n\n"
                "你是在「說」這個念頭，還是你「就是」那個念頭？\n\n"
                "這兩個有什麼不一樣嗎？"
            )
        elif step == 1:
            updates["step"] = 2
            reply = (
                "謝謝你願意停下來想這個。\n\n"
                f"接下來我想帶你用四個問題，一起看看「{belief}」這個念頭。\n\n"
                "你準備好了嗎？"
            )
        else:
            updates["phase"] = 2
            updates["step"] = 1
            reply = (
                f"好，我們開始。\n\n"
                f"第一個問題：\n\n**「{belief}」——這是真的嗎？**"
            )
        return reply, updates

    # ── Phase 2：四問本體 ──────────────────────────────────
    if phase == 2:
        belief = core_belief
        q_step = step  # 1=Q1, 2=Q2, 3=Q3, 4=Q4, 5=翻轉

        if q_step == 1:
            updates["step"] = 2
            prompt = f"""用戶剛回應了 Byron Katie 第一問「這是真的嗎？」
用戶回應：「{user_text}」
核心信念：「{belief}」

請給出第二問的引導（30-60字）：
- 先簡短承接用戶的回應（不評判）
- 接著問第二問：「你能絕對確定這是真的嗎？」
只回傳對話文字。"""

        elif q_step == 2:
            updates["step"] = 3
            prompt = f"""用戶剛回應了 Byron Katie 第二問「你能絕對確定嗎？」
用戶回應：「{user_text}」
核心信念：「{belief}」

請給出第三問的引導（40-70字）：
- 先簡短承接
- 問第三問：「當你相信『{belief}』這個念頭時，你有什麼反應？對自己、對別人、對生活？」
只回傳對話文字。"""

        elif q_step == 3:
            updates["step"] = 4
            prompt = f"""用戶剛回應了 Byron Katie 第三問（相信念頭時的反應）
用戶回應：「{user_text}」
核心信念：「{belief}」

請給出第四問的引導（40-70字）：
- 先簡短承接（可以說「聽起來這個念頭帶來了很多...」）
- 問第四問：「如果沒有這個念頭，你會是誰？你的生活會是什麼樣子？」
只回傳對話文字。"""

        elif q_step == 4:
            updates["step"] = 5
            prompt = f"""用戶剛回應了 Byron Katie 第四問（沒有念頭的自己）
用戶回應：「{user_text}」
核心信念：「{belief}」

請引導翻轉練習（50-80字）：
- 先承接用戶的回應
- 說明翻轉：「現在我們來翻轉一下這個念頭。把『{belief}』反過來說，你能找到三個讓你覺得反過來說也是真的理由嗎？」
只回傳對話文字。"""

        elif q_step == 5:
            updates["phase"] = 3
            updates["step"] = 0
            prompt = f"""用戶完成了 Byron Katie 四問法和翻轉練習。
用戶最後說：「{user_text}」
核心信念：「{belief}」

請給出結語（40-70字）：
- 感謝用戶的探索
- 反映用戶走過的過程
- 輕輕問：「現在再看這個念頭，感覺有什麼不一樣嗎？」
只回傳對話文字。"""

        else:
            return "謝謝你今天的探索。如果你想繼續，隨時可以說。", updates

        reply = await call_api(prompt)
        if not reply:
            reply = "謝謝你的回應。我們繼續往下看。"
        return reply, updates

    # ── Phase 3：結語 ──────────────────────────────────────
    return "謝謝你今天願意帶著這個念頭走了一趟。這份覺察，是你帶走的。", {}
