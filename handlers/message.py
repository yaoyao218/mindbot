from linebot.v3.messaging import (
    MessagingApi, ReplyMessageRequest,
    TextMessage, FlexMessage, FlexContainer
)
from linebot.v3.webhooks import MessageEvent
from services.session import get_session, save_session
from services.ai_label import analyze_message
from services.dialog import get_next_reply
import json


# 觸發關鍵字
CHECKIN_KEYWORDS = ["簽到", "check in", "checkin", "今天狀態"]
START_KEYWORDS = ["開始", "start", "你好", "hi", "hello", "嗨"]
HELP_KEYWORDS = ["說明", "help", "怎麼用", "功能"]


async def handle_message(event: MessageEvent, line_bot_api: MessagingApi):
    user_id = event.source.user_id
    text = event.message.text.strip()
    reply_token = event.reply_token

    # 關鍵字路由
    if any(kw in text.lower() for kw in CHECKIN_KEYWORDS):
        await send_checkin_flex(reply_token, line_bot_api)
        return

    if any(kw in text.lower() for kw in START_KEYWORDS):
        await send_welcome(reply_token, line_bot_api)
        return

    if any(kw in text.lower() for kw in HELP_KEYWORDS):
        await send_help(reply_token, line_bot_api)
        return

    # 取得用戶 session
    session = await get_session(user_id)

    # 有進行中的簽到（等待自由輸入補充）
    if session.get("pending_checkin"):
        await handle_checkin_supplement(
            event, line_bot_api, session, text
        )
        return

    # 有進行中的對話
    if session.get("in_dialog"):
        reply = await get_next_reply(session, text, user_id)
        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=reply)]
            )
        )
        return

    # 一般訊息 → AI 分析 → 開始對話
    labels = await analyze_message(text)
    session["labels"] = labels
    session["in_dialog"] = True
    session["method"] = labels.get("suggested_method", "BYRON_KATIE")
    session["step"] = 0
    session["core_belief"] = labels.get("core_belief")
    session["history"] = [{"role": "user", "text": text}]

    await save_session(user_id, session)

    reply = await get_next_reply(session, text, user_id)
    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=reply)]
        )
    )


async def handle_checkin_supplement(
    event, line_bot_api, session, text
):
    from services.ai_label import analyze_checkin
    from services.db import save_checkin

    user_id = event.source.user_id
    reply_token = event.reply_token
    pending = session["pending_checkin"]

    if text == "跳過":
        # 只儲存情緒標籤
        await save_checkin(user_id, {
            "emotion": pending["emotion"],
            "timestamp": pending["timestamp"]
        })
        session.pop("pending_checkin")
        await save_session(user_id, session)

        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text="已記錄 ✓\n\n如果之後想聊聊，隨時傳訊息給我。")]
            )
        )
    else:
        # AI 分析自由輸入
        result = await analyze_checkin(text, pending["emotion"])
        await save_checkin(user_id, {
            "emotion": pending["emotion"],
            "cognition": result.get("cognition"),
            "need": result.get("need"),
            "user_text": text,
            "timestamp": pending["timestamp"]
        })
        session.pop("pending_checkin")
        await save_session(user_id, session)

        reflection = result.get("reflection", "謝謝你願意說出來。")
        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(
                    text=f"已記錄 ✓\n\n{reflection}"
                )]
            )
        )


async def send_welcome(reply_token: str, line_bot_api: MessagingApi):
    msg = (
        "嗨，我是心事日記 🌿\n\n"
        "我可以陪你整理心裡的想法，"
        "用提問的方式幫你看清楚困擾你的事。\n\n"
        "你可以：\n"
        "• 直接說出你在煩惱的事\n"
        "• 輸入「簽到」記錄今天的狀態\n"
        "• 輸入「說明」了解更多功能"
    )
    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=msg)]
        )
    )


async def send_help(reply_token: str, line_bot_api: MessagingApi):
    msg = (
        "📖 使用說明\n\n"
        "【開始對話】\n"
        "直接說出你的煩惱，我會陪你一起看清楚。\n\n"
        "【每日簽到】\n"
        "輸入「簽到」記錄今天的心情狀態。\n\n"
        "【隨時開始】\n"
        "不需要特別的格式，就像跟朋友說話一樣。"
    )
    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=msg)]
        )
    )


async def send_checkin_flex(reply_token: str, line_bot_api: MessagingApi):
    flex_content = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "今天的你，比較像哪一種？",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#1D9E75"
                },
                {
                    "type": "text",
                    "text": "選一個最接近現在感受的選項",
                    "size": "sm",
                    "color": "#888888",
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
                    "type": "button",
                    "action": {
                        "type": "postback",
                        "label": "😰 很崩潰，快撐不住了",
                        "data": "action=checkin&emotion=ACUTE_DISTRESS"
                    },
                    "style": "secondary",
                    "height": "sm"
                },
                {
                    "type": "button",
                    "action": {
                        "type": "postback",
                        "label": "🔁 一件事一直在腦袋裡轉",
                        "data": "action=checkin&emotion=RUMINATION"
                    },
                    "style": "secondary",
                    "height": "sm"
                },
                {
                    "type": "button",
                    "action": {
                        "type": "postback",
                        "label": "😞 覺得都是自己的錯",
                        "data": "action=checkin&emotion=SELF_BLAME"
                    },
                    "style": "secondary",
                    "height": "sm"
                },
                {
                    "type": "button",
                    "action": {
                        "type": "postback",
                        "label": "😶 說不清楚，就是哪裡不對",
                        "data": "action=checkin&emotion=CONFUSION"
                    },
                    "style": "secondary",
                    "height": "sm"
                },
                {
                    "type": "button",
                    "action": {
                        "type": "postback",
                        "label": "🧘 還好，心情比較平穩",
                        "data": "action=checkin&emotion=CALM_REFLECTIVE"
                    },
                    "style": "primary",
                    "color": "#1D9E75",
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
                    alt_text="今天的你，比較像哪一種？",
                    contents=FlexContainer.from_dict(flex_content)
                )
            ]
        )
    )
