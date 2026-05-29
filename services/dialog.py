"""
對話引擎 - MVP 階段先實作 Byron Katie 四問法
後續加入其他三種方法
"""

from services.session import save_session


# Byron Katie 四問腳本
BYRON_KATIE_STEPS = [
    # Step 0：確認核心信念
    lambda belief: (
        f"我聽到了。\n\n"
        f"你說「{belief}」\n\n"
        f"讓我們慢慢看看這個想法。\n\n"
        f"第一個問題：\n"
        f"這是真的嗎？"
    ),
    # Step 1：追問確定性
    lambda belief: (
        f"你能絕對確定「{belief}」是真的嗎？\n\n"
        f"有沒有任何例外的可能？"
    ),
    # Step 2：觀察影響
    lambda belief: (
        f"當你相信「{belief}」這個想法的時候，\n"
        f"你有什麼反應？\n\n"
        f"你怎麼對待自己？你的生活發生了什麼？"
    ),
    # Step 3：想像沒有這個念頭
    lambda belief: (
        f"如果沒有「{belief}」這個念頭，\n"
        f"你會是誰？你的生活會是什麼樣子？"
    ),
    # Step 4：翻轉
    lambda belief: (
        f"最後一個問題——\n\n"
        f"「{belief}」\n\n"
        f"把這句話翻過來說，\n"
        f"你能找到至少三個理由，說明翻轉後的句子也是真的嗎？"
    ),
]

# SQT 腳本
SQT_STEPS = [
    lambda _: "你現在腦袋裡一直出現什麼念頭？用一句話說說看。",
    lambda _: (
        "好。現在專注在這句話上。\n\n"
        "這個念頭，是誰在說？\n"
        "它現在在你身體的哪個位置？"
    ),
    lambda _: (
        "你能不能只是看著它，不跟著它走？\n\n"
        "它說它的，你看著它說。\n"
        "現在感覺怎麼樣？"
    ),
    lambda _: (
        "那個念頭還在嗎？\n\n"
        "如果在，它的力道有沒有比剛才輕一點？"
    ),
]

# 結束語
CLOSING_MESSAGE = (
    "謝謝你今天願意陪自己走這一段 🙏\n\n"
    "這些想法不會消失，但你剛才已經用不一樣的方式看了它們。\n\n"
    "如果之後還有想聊的，隨時傳訊息給我。"
)


async def get_next_reply(session: dict, user_text: str, user_id: str) -> str:
    """根據當前 session 狀態回傳下一句對話"""

    method = session.get("method", "BYRON_KATIE")
    step = session.get("step", 0)

    # 更新對話歷史
    session["history"].append({"role": "user", "text": user_text})

    # pre-step：從簽到深度對話進來，先收集核心困擾再開始提問
    if step == -1:
        session["core_belief"] = user_text
        session["step"] = 0
        step = 0

    core_belief = session.get("core_belief") or user_text

    # 選擇方法腳本
    if method == "BYRON_KATIE":
        steps = BYRON_KATIE_STEPS
    elif method == "SQT":
        steps = SQT_STEPS
    else:
        steps = BYRON_KATIE_STEPS  # 預設

    # 對話結束
    if step >= len(steps):
        session["in_dialog"] = False
        session["step"] = 0
        await save_session(user_id, session)
        return CLOSING_MESSAGE

    # 取得當前步驟回覆
    reply_fn = steps[step]
    reply = reply_fn(core_belief)

    # 更新步驟
    session["step"] = step + 1
    session["history"].append({"role": "bot", "text": reply})
    await save_session(user_id, session)

    return reply
