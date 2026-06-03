from linebot.v3.messaging import (
    MessagingApi, ReplyMessageRequest, TextMessage,
    FlexMessage, FlexContainer
)
from linebot.v3.webhooks import PostbackEvent
from services.session import get_session, save_session
import time

# 使用 db_persistent 版本的 session（有持久化）
async def _get_session(user_id):
    try:
        import services.db_persistent as _dbp
        return await _dbp.get_session(user_id)
    except Exception:
        return await get_session(user_id)

async def _save_session(user_id, session):
    try:
        import services.db_persistent as _dbp
        await _dbp.save_session(user_id, session)
    except Exception:
        await save_session(user_id, session)


EMOTION_LABELS = {
    "ACUTE_DISTRESS":  "很崩潰，快撐不住了",
    "RUMINATION":      "一件事一直在腦袋裡轉",
    "SELF_BLAME":      "覺得都是自己的錯",
    "CONFUSION":       "說不清楚，就是哪裡不對",
    "CALM_REFLECTIVE": "心情比較平穩",
}

EMOTION_TO_METHOD = {
    "ACUTE_DISTRESS":  "SQT",
    "RUMINATION":      "SQT",
    "SELF_BLAME":      "BYRON_KATIE",
    "CONFUSION":       "BYRON_KATIE",
    "CALM_REFLECTIVE": "BYRON_KATIE",
}

# 簽到情緒 → (塔羅用中文名, arousal)
CHECKIN_EMOTION_TO_CN = {
    "ACUTE_DISTRESS":  ("焦慮",    4),
    "RUMINATION":      ("迷茫",    3),
    "SELF_BLAME":      ("自我懷疑", 3),
    "CONFUSION":       ("迷茫",    2),
    "CALM_REFLECTIVE": ("平靜",    1),
}


async def handle_postback(event: PostbackEvent, line_bot_api: MessagingApi):
    user_id = event.source.user_id
    reply_token = event.reply_token
    data = event.postback.data

    params = dict(p.split("=") for p in data.split("&") if "=" in p)
    action = params.get("action")

    if action == "checkin":
        await handle_checkin_selection(user_id, reply_token, params, line_bot_api)
    elif action == "checkin_action":
        await handle_checkin_action(user_id, reply_token, params, line_bot_api)
    elif action == "tarot_flip":
        await handle_tarot_flip(user_id, reply_token, line_bot_api)
    elif action == "onboard":
        await handle_onboard(user_id, reply_token, params, line_bot_api)
    elif action == "set_context":
        await handle_set_context(user_id, reply_token, params, line_bot_api)


async def handle_onboard(
    user_id: str,
    reply_token: str,
    params: dict,
    line_bot_api: MessagingApi
):
    from handlers.onboarding import send_feature_menu, send_feature_detail, send_start_reply
    page = params.get("page", "menu")
    if page == "menu":
        await send_feature_menu(reply_token, line_bot_api)
    elif page == "start":
        await send_start_reply(reply_token, line_bot_api)
    else:
        await send_feature_detail(page, reply_token, line_bot_api)


async def handle_checkin_selection(
    user_id: str,
    reply_token: str,
    params: dict,
    line_bot_api: MessagingApi
):
    emotion = params.get("emotion", "")
    label_text = EMOTION_LABELS.get(emotion, "")

    session = await get_session(user_id)
    session["pending_checkin"] = {
        "emotion": emotion,
        "timestamp": int(time.time() * 1000),
    }
    await save_session(user_id, session)

    flex_content = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "收到了 🙏",
                    "weight": "bold",
                    "size": "md",
                    "color": "#1D9E75"
                },
                {
                    "type": "text",
                    "text": f"「{label_text}」",
                    "size": "sm",
                    "color": "#555555",
                    "margin": "sm"
                }
            ],
            "backgroundColor": "#F0FAF6",
            "paddingAll": "16px"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "text",
                    "text": "接下來你想做什麼？",
                    "size": "md",
                    "weight": "bold",
                    "color": "#333333",
                    "margin": "none"
                },
                {
                    "type": "text",
                    "text": "選一個最符合你現在需要的選項",
                    "size": "sm",
                    "color": "#888888",
                    "margin": "sm"
                },
                {
                    "type": "button",
                    "action": {
                        "type": "postback",
                        "label": "💬 深度對話，整理這個感受",
                        "data": f"action=checkin_action&choice=dialog&emotion={emotion}",
                        "displayText": "我想深度對話"
                    },
                    "style": "primary",
                    "color": "#1D9E75",
                    "height": "sm",
                    "margin": "lg"
                },
                {
                    "type": "button",
                    "action": {
                        "type": "postback",
                        "label": "✍️ 寫幾個字，記錄今天發生的事",
                        "data": f"action=checkin_action&choice=note&emotion={emotion}",
                        "displayText": "我想寫幾個字記錄"
                    },
                    "style": "secondary",
                    "height": "sm"
                },
                {
                    "type": "button",
                    "action": {
                        "type": "postback",
                        "label": "✅ 只記錄今天的情緒狀態",
                        "data": f"action=checkin_action&choice=record&emotion={emotion}",
                        "displayText": "只記錄今天狀態"
                    },
                    "style": "secondary",
                    "height": "sm"
                }
            ],
            "paddingAll": "16px"
        }
    }

    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[
                FlexMessage(
                    alt_text="接下來你想做什麼？",
                    contents=FlexContainer.from_dict(flex_content)
                )
            ]
        )
    )


async def handle_checkin_action(
    user_id: str,
    reply_token: str,
    params: dict,
    line_bot_api: MessagingApi
):
    choice = params.get("choice")
    emotion = params.get("emotion", "")
    session = await get_session(user_id)

    if choice == "dialog":
        method = EMOTION_TO_METHOD.get(emotion, "BYRON_KATIE")
        session.pop("pending_checkin", None)
        session["in_dialog"] = True
        session["method"] = method
        session["step"] = -1   # pre-step：等待用戶說出核心困擾
        session["core_belief"] = None
        session["history"] = []
        await save_session(user_id, session)

        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(
                    text=(
                        "好，讓我們慢慢看看 🌿\n\n"
                        "讓你有這樣感受的，是什麼事情或什麼念頭？\n"
                        "用幾個字說說看就好。"
                    )
                )]
            )
        )

    elif choice == "note":
        if session.get("pending_checkin"):
            session["pending_checkin"]["mode"] = "note"
            await save_session(user_id, session)

        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(
                    text=(
                        "用幾個字描述今天發生的事，或你現在的感受。\n"
                        "（傳「跳過」可以略過）"
                    )
                )]
            )
        )

    elif choice == "record":
        from services.db import save_checkin
        import datetime as _dt
        pending = session.get("pending_checkin", {})
        await save_checkin(user_id, {
            "emotion": emotion,
            "timestamp": pending.get("timestamp", int(time.time() * 1000))
        })
        session.pop("pending_checkin", None)
        await save_session(user_id, session)

        # 指派塔羅 + 儲存情緒月曆
        tarot_text = ""
        try:
            from services.symbolic import assign_tarot_structured, format_tarot_reply
            from services.nudge import infer_emotion_emoji
            from services.db_persistent import save_emotion_calendar
            emotion_cn, arousal_val = CHECKIN_EMOTION_TO_CN.get(emotion, ("平靜", 1))
            tarot = assign_tarot_structured(emotion_cn, arousal_val)
            emoji, label = await infer_emotion_emoji([], emotion)
            await save_emotion_calendar(
                user_id, _dt.date.today(), emoji, label,
                tarot_card=tarot.get("card_name"),
                tarot_meaning=tarot.get("meaning"),
                tarot_reversed=tarot.get("is_reversed", False),
            )
            tarot_text = format_tarot_reply(tarot)
        except Exception as e:
            print(f"[postback] tarot assign failed: {e}")

        reply_body = "已記錄 ✓"
        if tarot_text:
            reply_body += f"\n\n{tarot_text}"
        else:
            reply_body += "\n\n如果之後想聊聊，隨時傳訊息給我。"

        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=reply_body)]
            )
        )


async def handle_tarot_flip(
    user_id: str,
    reply_token: str,
    line_bot_api: MessagingApi,
):
    """用戶點擊「翻牌」Postback → 揭示牌面 + AI 投射問句"""
    session = await _get_session(user_id)
    card = session.pop("pending_tarot_flip", None)

    if not card:
        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text="牌已經翻過了，有什麼想說的嗎？")]
            )
        )
        return

    await _save_session(user_id, session)

    try:
        from services.tarot_projective import get_projective_question, build_revealed_card_flex
        emotion = session.get("psych", {}).get("emotion", "迷茫")
        question = await get_projective_question(card, emotion)
        flex = build_revealed_card_flex(card, question)
        card_name = card.get("card_name", "？")
        pos = "逆位" if card.get("is_reversed") else "正位"
        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[FlexMessage(
                    alt_text=f"為你翻開了【{card_name}・{pos}】",
                    contents=FlexContainer.from_dict(flex)
                )]
            )
        )
    except Exception as e:
        print(f"[TarotFlip] Error: {e}")
        card_name = card.get("card_name", "一張牌")
        meaning   = card.get("meaning", "")
        pos = "逆位" if card.get("is_reversed") else "正位"
        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(
                    text=f"【{card_name}・{pos}】\n{meaning}\n\n這張牌讓你想到了什麼？"
                )]
            )
        )


async def handle_set_context(
    user_id: str,
    reply_token: str,
    params: dict,
    line_bot_api: MessagingApi,
):
    """
    用戶選擇對話情境：
      deep  → 睡前深度陪伴（完整四步對話，最多不限輪數）
      quick → 通勤快速打卡（3 輪後自動觸發 SummaryModule）
    """
    value = params.get("value", "deep")
    session = await _get_session(user_id)
    session["current_context"] = value
    session["in_dialog"]       = True
    session["history"]         = session.get("history", [])
    await _save_session(user_id, session)

    if value == "quick":
        reply = (
            "好，我們快速聊三個重點 🏃\n\n"
            "現在最想說的一件事是什麼？"
        )
    else:
        reply = (
            "好，今晚我們慢慢說 🌙\n\n"
            "現在腦子裡有什麼事放不下？"
        )

    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=reply)]
        )
    )
