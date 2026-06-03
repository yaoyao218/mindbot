"""
前期引導系統 — Follow 事件 + 功能選單 Flex Messages
規格：前期引導系統設計 v1.0
"""

from linebot.v3.messaging import (
    MessagingApi, ReplyMessageRequest, PushMessageRequest,
    TextMessage, FlexMessage, FlexContainer
)

APP_URL = "https://web-production-dd506.up.railway.app"

# ── 色彩常數 ─────────────────────────────────────────────────
_GREEN   = "#1D9E75"
_BG      = "#F0FAF6"
_GRAY    = "#888888"
_DARK    = "#333333"
_LIGHT_BORDER = "#E0F2EC"


# ════════════════════════════════════════════════════════════
# 歡迎訊息（純文字，跟在 Follow 事件後送出）
# ════════════════════════════════════════════════════════════

WELCOME_TEXT = (
    "嗨，我是心事日記 🌙\n\n"
    "這裡是你的私人空間——\n"
    "不用說得完整，不用解釋清楚，\n"
    "想說什麼就說什麼，我會好好聽。\n\n"
    "在開始之前，想讓你知道這裡有什麼："
)


# ════════════════════════════════════════════════════════════
# 功能選單 Flex Message
# ════════════════════════════════════════════════════════════

def _feature_menu_flex() -> FlexMessage:
    content = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": _BG,
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "text",
                    "text": "心事日記 能為你做什麼？",
                    "weight": "bold",
                    "size": "lg",
                    "color": _GREEN,
                    "align": "center"
                },
                {
                    "type": "text",
                    "text": "點選任一項目了解詳情",
                    "size": "xs",
                    "color": _GRAY,
                    "align": "center",
                    "margin": "sm"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                _menu_btn("🌙 每日陪伴對話", "daily"),
                _menu_btn("📅 情緒日記與月曆", "diary"),
                _menu_btn("📊 互動回饋與里程碑", "feedback"),
                _menu_btn("🌐 個人分析網站", "website"),
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "12px",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "postback",
                        "label": "▶  我準備好了，開始吧",
                        "data": "action=onboard&page=start",
                        "displayText": "開始使用心事日記"
                    },
                    "style": "primary",
                    "color": _GREEN,
                    "height": "sm"
                }
            ]
        }
    }
    return FlexMessage(
        alt_text="心事日記 能為你做什麼？",
        contents=FlexContainer.from_dict(content)
    )


def _menu_btn(label: str, page: str) -> dict:
    return {
        "type": "button",
        "action": {
            "type": "postback",
            "label": label,
            "data": f"action=onboard&page={page}",
            "displayText": label
        },
        "style": "secondary",
        "height": "sm"
    }


# ════════════════════════════════════════════════════════════
# 各功能說明 Flex Messages
# ════════════════════════════════════════════════════════════

def _back_btn() -> dict:
    """返回選單按鈕"""
    return {
        "type": "button",
        "action": {
            "type": "postback",
            "label": "← 返回選單",
            "data": "action=onboard&page=menu",
            "displayText": "返回功能選單"
        },
        "style": "secondary",
        "height": "sm",
        "color": _GRAY
    }


def _text_row(text: str, size: str = "sm", color: str = None, margin: str = "sm") -> dict:
    row = {
        "type": "text",
        "text": text,
        "wrap": True,
        "size": size,
        "color": color or "#555555",
        "margin": margin
    }
    return row


def _daily_detail_flex() -> FlexMessage:
    content = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": _BG,
            "paddingAll": "20px",
            "contents": [
                {"type": "text", "text": "每日陪伴對話 🌙",
                 "weight": "bold", "size": "lg", "color": _GREEN}
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "20px",
            "spacing": "md",
            "contents": [
                _text_row("不知道說什麼沒關係——", "sm", "#333333", "none"),
                _text_row("每晚我會主動送出一個問題，\n你只需要回應那一句就好。"),
                _text_row("也可以隨時打開來說，\n不用完整，不用有結論。"),
                _text_row("說出來，就是在照顧自己。", "sm", _GREEN, "lg"),
                {
                    "type": "separator",
                    "margin": "lg",
                    "color": _LIGHT_BORDER
                },
                _text_row("💡 推播設定：傳送「設定推播 21:00」\n可以自訂每天收到問題的時間。",
                          "xs", _GRAY, "md")
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "12px",
            "contents": [_back_btn()]
        }
    }
    return FlexMessage(
        alt_text="每日陪伴對話",
        contents=FlexContainer.from_dict(content)
    )


def _diary_detail_flex() -> FlexMessage:
    content = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": _BG,
            "paddingAll": "20px",
            "contents": [
                {"type": "text", "text": "情緒日記與月曆 📅",
                 "weight": "bold", "size": "lg", "color": _GREEN}
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "20px",
            "spacing": "md",
            "contents": [
                _text_row("每次對話結束後，\n我會自動記錄你今天的情緒狀態。", "sm", "#333333", "none"),
                _text_row("你可以在網站上看到：", "sm", _DARK, "md"),
                _text_row("・每日情緒月曆（emoji 走勢）\n・本月情緒分佈\n・你最常說到的主題", "sm", "#555555", "xs"),
                _text_row("傳送「簽到」可以記錄今天。", "sm", _GREEN, "lg"),
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "12px",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "🌐 查看我的情緒月曆",
                        "uri": f"{APP_URL}/app#calendar"
                    },
                    "style": "primary",
                    "color": _GREEN,
                    "height": "sm"
                },
                _back_btn()
            ]
        }
    }
    return FlexMessage(
        alt_text="情緒日記與月曆",
        contents=FlexContainer.from_dict(content)
    )


def _feedback_detail_flex() -> FlexMessage:
    content = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": _BG,
            "paddingAll": "20px",
            "contents": [
                {"type": "text", "text": "互動回饋與里程碑 📊",
                 "weight": "bold", "size": "lg", "color": _GREEN}
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "20px",
            "spacing": "md",
            "contents": [
                _text_row("每當你說完一次心事，我就會記下來。", "sm", "#333333", "none"),
                _text_row("到了某個時刻，\n我會整理這段時間你最常說到的主題，\n用一句話告訴你我觀察到的事。"),
                _text_row("不是評價，不是建議，\n只是讓你看見自己一直在。", "sm", _GREEN, "lg"),
                {
                    "type": "separator",
                    "margin": "lg",
                    "color": _LIGHT_BORDER
                },
                _text_row("🌱 第 7 天 ・ 🌿 第 14 天 ・ 🌙 第 30 天\n都會收到里程碑回顧",
                          "xs", _GRAY, "md")
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "12px",
            "contents": [_back_btn()]
        }
    }
    return FlexMessage(
        alt_text="互動回饋與里程碑",
        contents=FlexContainer.from_dict(content)
    )


def _website_detail_flex() -> FlexMessage:
    content = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": _BG,
            "paddingAll": "20px",
            "contents": [
                {"type": "text", "text": "個人分析網站 🌐",
                 "weight": "bold", "size": "lg", "color": _GREEN}
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "20px",
            "spacing": "md",
            "contents": [
                _text_row("所有的對話和情緒記錄，\n都會整理成你專屬的分析頁面。", "sm", "#333333", "none"),
                _text_row("網站上可以看到：", "sm", _DARK, "md"),
                _text_row(
                    "・情緒月曆與走勢\n・本週 / 本月關鍵詞\n・對話里程碑回顧\n・每週摘要報告",
                    "sm", "#555555", "xs"
                ),
                _text_row(APP_URL.replace("https://", ""), "xs", _GRAY, "lg")
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "12px",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "前往個人分析網站",
                        "uri": f"{APP_URL}/app"
                    },
                    "style": "primary",
                    "color": _GREEN,
                    "height": "sm"
                },
                _back_btn()
            ]
        }
    }
    return FlexMessage(
        alt_text="個人分析網站",
        contents=FlexContainer.from_dict(content)
    )


# ════════════════════════════════════════════════════════════
# 公開 API
# ════════════════════════════════════════════════════════════

FEATURE_FLEX_MAP = {
    "daily":    _daily_detail_flex,
    "diary":    _diary_detail_flex,
    "feedback": _feedback_detail_flex,
    "website":  _website_detail_flex,
}


async def send_welcome(user_id: str, line_bot_api: MessagingApi) -> None:
    """Follow 事件：送出歡迎文字 + 功能選單（兩則訊息）"""
    await line_bot_api.push_message(
        PushMessageRequest(
            to=user_id,
            messages=[
                TextMessage(text=WELCOME_TEXT),
                _feature_menu_flex(),
            ]
        )
    )


async def send_feature_menu(reply_token: str, line_bot_api: MessagingApi) -> None:
    """返回功能選單"""
    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[_feature_menu_flex()]
        )
    )


async def send_feature_detail(
    page: str,
    reply_token: str,
    line_bot_api: MessagingApi
) -> None:
    """送出指定功能的詳細說明"""
    fn = FEATURE_FLEX_MAP.get(page)
    if fn:
        flex = fn()
    else:
        flex = _feature_menu_flex()

    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[flex]
        )
    )


async def send_start_reply(reply_token: str, line_bot_api: MessagingApi) -> None:
    """「我準備好了」→ 開始引導"""
    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[
                TextMessage(text=(
                    "好，我在這裡 🌙\n\n"
                    "想說什麼就說，\n"
                    "或者等今晚的問題來找你。\n\n"
                    "（你也可以傳「簽到」記錄今天的開始）"
                ))
            ]
        )
    )
