from services.llm import call_api
"""
後設認知療法（MCT）對話模組
Phase 0: 正向後設認知信念評估
Phase 1: 反芻行為實驗（有正向信念才執行）
Phase 2: MCT 主體四步（計畫→執行→監控→評估）
"""



async def assess_positive_metacognition(user_text: str) -> bool:
    """
    Phase 0：偵測正向後設認知信念
    「一直想對我有幫助」「多想想才能解決」
    """
    prompt = f"""判斷用戶是否相信「持續思考/反芻對解決問題有幫助」。
只回傳 JSON：{{"has_positive_metacognition": true}} 或 {{"has_positive_metacognition": false}}

用戶訊息：「{user_text}」

跡象包括：說自己需要「想清楚」、「多想想」、「不能不想」、「想通了才能放下」"""

    try:
        raw = await call_api(prompt, max_tokens=80, tier="haiku")
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw).get("has_positive_metacognition", False)
    except Exception:
        return False


async def get_reply(session: dict, user_text: str) -> tuple[str, dict]:
    """
    主入口：依 session phase/step 回傳下一步
    """
    phase = session.get("phase", 0)
    step = session.get("step", 0)
    updates = {}

    # ── Phase 0：評估正向後設認知信念 ──────────────────────
    if phase == 0:
        has_pmb = await assess_positive_metacognition(user_text)
        if has_pmb:
            updates["phase"] = 1
            updates["step"] = 0
            updates["has_positive_metacognition"] = True
            reply = (
                "我注意到你說到一直在想這件事。\n\n"
                "我想問你一個問題：\n\n"
                "你覺得「一直想這件事」對你有什麼幫助呢？"
            )
        else:
            updates["phase"] = 2
            updates["step"] = 1
            prompt = f"""用戶說：「{user_text}」
這是後設認知治療的第一輪。

請給出 Phase 2 Step 1「計畫」的引導（50-70字）：
- 先簡短傾聽
- 問：「你最想從這段對話裡得到什麼？是想理清楚事情的脈絡，還是讓腦袋停一下？」
只回傳對話文字。"""
            reply = await call_api(prompt)
            return reply or "我在聽。你最想從這段對話裡得到什麼？", updates
        return reply, updates

    # ── Phase 1：反芻行為實驗 ──────────────────────────────
    if phase == 1:
        if step == 0:
            updates["step"] = 1
            prompt = f"""用戶解釋了「一直想」對他有什麼幫助：「{user_text}」

請給出 Phase 1 Step B 的引導（60-80字）：
- 先好奇地承接用戶的答案
- 提出行為實驗：
  「我想邀請你試一個小實驗：這一天讓自己盡量想這件事，明天試試刻意減少想它，
   然後比較看看——哪天你感覺比較能往前走？」
只回傳對話文字。"""
            reply = await call_api(prompt)
            return reply or "好的，我聽到了。我想邀請你試個小實驗：今天讓自己盡量想這件事，明天刻意少想，然後比較看看哪天你狀態比較好？", updates

        elif step == 1:
            updates["phase"] = 2
            updates["step"] = 1
            prompt = f"""用戶回應了行為實驗的邀請：「{user_text}」

請給出過渡到 MCT 主體的回應（40-60字）：
- 承接用戶的回應
- 說：「好，那我們來看看這件事本身。你最想先弄清楚哪個部分？」
只回傳對話文字。"""
            reply = await call_api(prompt)
            return reply or "好，那我們來看看這件事本身。你最想先弄清楚哪個部分？", updates

    # ── Phase 2：MCT 主體四步 ──────────────────────────────
    if phase == 2:
        if step == 1:  # 計畫
            updates["step"] = 2
            prompt = f"""用戶說：「{user_text}」
MCT Step 2「執行」：幫助用戶區分「事實」與「解讀/想法」。

請給出引導（60-80字）：
- 先承接
- 說：「我們來試著分一下：在這件事裡，哪些是確實發生的事實？
  哪些是你對這件事的解讀或想法？」
只回傳對話文字。"""
            reply = await call_api(prompt)
            return reply or "我們來試著分一下：這件事裡，哪些是確實發生的事實？哪些是你對它的解讀？", updates

        if step == 2:  # 執行
            updates["step"] = 3
            prompt = f"""用戶嘗試區分了事實與解讀：「{user_text}」
MCT Step 3「監控」：介紹分離式正念（Detached Mindfulness）。

請給出引導（70-90字）：
- 先承接用戶的區分
- 介紹分離式正念：
  「現在試試看一件事：讓這些念頭在那裡，不跟它說話，也不推開它。
   就像路邊走過的陌生人——你看到了，但你繼續走你的路。
   你能試試這個感覺嗎？」
只回傳對話文字。"""
            reply = await call_api(prompt)
            return reply or "好，你區分了事實和解讀。現在試試：讓這些念頭在那裡，不跟它說話也不推開它——就像路邊走過的陌生人。你試試看這個感覺？", updates

        if step == 3:  # 監控
            updates["step"] = 4
            prompt = f"""用戶體驗了分離式正念：「{user_text}」
MCT Step 4「評估」：重新評估反芻的代價與控制感。

請給出引導（60-80字）：
- 先承接用戶的體驗
- 問：「回頭看看你之前說的反芻/一直想——
  現在你覺得這樣的思考方式，幫你更靠近你想要的結果了嗎？
  還是讓你離得更遠？」
只回傳對話文字。"""
            reply = await call_api(prompt)
            return reply or "謝謝你試了這個。回頭看看你之前一直在想的事——這樣的方式，讓你更靠近你想要的嗎？還是更遠？", updates

        if step == 4:  # 評估
            updates["step"] = 5
            prompt = f"""用戶完成了 MCT 四步評估。用戶說：「{user_text}」

請給出溫暖的結語（50-70字）：
- 反映用戶走過的歷程
- 問：「如果下次那個反芻的念頭又來了，你現在有沒有多了一點空間去回應它？」
只回傳對話文字。"""
            reply = await call_api(prompt)
            return reply or "謝謝你今天走過這些。下次反芻的念頭又來時，你覺得自己多了一點空間去回應它嗎？", updates

    return "謝謝你今天的探索。如果那個念頭又開始轉，記得可以讓它在那裡，你繼續走你的路。", {}
