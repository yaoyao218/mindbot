from urllib.parse import parse_qs
from linebot.v3.messaging import (
    MessagingApi, ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import PostbackEvent
from services.session import get_session, save_session
import time


async def handle_postback(event: PostbackEvent, line_bot_api: MessagingApi):
    user_id = event.source.user_id
    reply_token = event.reply_token
    data = event.postback.data

    # 解析 postback data
    params = dict(p.split("=") for p in data.split("&") if "=" in p)
    action = params.get("action")

    if action == "checkin":
        await handle_checkin_selection(
            user_id, reply_token, params, line_bot_api
        )


async def handle_checkin_selection(
    user_id: str,
    reply_token: str,
    params: dict,
    line_bot_api: MessagingApi
):
    emotion = params.get("emotion", "")

    emotion_labels = {
        "ACUTE_DISTRESS":   "很崩潰，快撐不住了",
        "RUMINATION":       "一件事一直在腦袋裡轉",
        "SELF_BLAME":       "覺得都是自己的錯",
        "CONFUSION":        "說不清楚，就是哪裡不對",
        "CALM_REFLECTIVE":  "心情比較平穩"
    }

    label_text = emotion_labels.get(emotion, "")

    # 儲存待處理的簽到（等待自由輸入補充）
    session = await get_session(user_id)
    session["pending_checkin"] = {
        "emotion": emotion,
        "timestamp": int(time.time() * 1000)
    }
    await save_session(user_id, session)

    reply = (
        f"收到了 🙏\n「{label_text}」\n\n"
        "想多說一點嗎？\n"
        "用幾個字描述今天發生的事，或傳「跳過」就好。"
    )

    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=reply)]
        )
    )
