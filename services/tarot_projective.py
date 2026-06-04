"""
tarot_projective.py — 塔羅投射模組

兩個功能：
1. 塔羅緩衝區：當用戶敷衍回覆時，發送覆蓋牌 Flex → 用戶翻牌 → AI 投射問句
2. 名言字卡收尾：對話結束時，發送精美的 Flex Message 字卡封存今日心事
"""

import os
from services.llm import call_api

LIFF_URL = "https://liff.line.me/2010279401-zI4pqH8D"
APP_URL  = os.environ.get("APP_URL", LIFF_URL)

# ══════════════════════════════════════════════════════════
# 1. 覆蓋牌 Flex（翻牌前）
# ══════════════════════════════════════════════════════════

def build_covered_card_flex() -> dict:
    """
    發送一張「覆蓋中」的塔羅牌 Flex Message。
    用戶點擊後觸發 Postback action=tarot_flip。
    """
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "backgroundColor": "#0f1410",
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "text",
                    "text": "心事日記",
                    "size": "xs",
                    "color": "#4a7c59",
                    "weight": "bold",
                    "letterSpacing": "4px",
                },
                {
                    "type": "text",
                    "text": "偵測到你現在可能有點累、\n或不知道該說什麼。",
                    "size": "sm",
                    "color": "#a89880",
                    "wrap": True,
                    "margin": "sm",
                },
                {
                    "type": "text",
                    "text": "沒關係，我們不聊壓力，\n先抽一張牌吧 🔮",
                    "size": "sm",
                    "color": "#e8e0d0",
                    "wrap": True,
                    "margin": "xs",
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "xl",
                    "spacing": "none",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "vertical",
                            "height": "120px",
                            "justifyContent": "center",
                            "alignItems": "center",
                            "backgroundColor": "#161c18",
                            "cornerRadius": "10px",
                            "borderWidth": "1px",
                            "borderColor": "#c9a84c40",
                            "contents": [
                                {
                                    "type": "text",
                                    "text": "🎴",
                                    "size": "4xl",
                                    "align": "center",
                                },
                                {
                                    "type": "text",
                                    "text": "點我翻牌",
                                    "size": "xs",
                                    "color": "#c9a84c",
                                    "align": "center",
                                    "margin": "sm",
                                    "letterSpacing": "2px",
                                },
                            ],
                            "action": {
                                "type": "postback",
                                "label": "翻牌",
                                "data": "action=tarot_flip",
                                "displayText": "（翻開塔羅牌）",
                            },
                        }
                    ],
                },
            ],
        },
    }


# ══════════════════════════════════════════════════════════
# 2. 揭示牌 Flex（翻牌後 + 投射問句）
# ══════════════════════════════════════════════════════════

async def generate_dialogue_insight(history: list[dict]) -> str:
    """
    AI（Haiku）將本次對話濃縮成 30–50 字的洞察摘要。
    用戶文字優先，以溫柔觀察者視角描述核心情緒動態。
    """
    user_texts = [h.get("text", "") for h in history if h.get("role") == "user"]
    if not user_texts:
        return ""
    sample = "\n".join(user_texts[-12:])

    prompt = f"""以下是用戶在這次對話中說的話：

{sample}

請用繁體中文，30–50 字，以溫柔觀察者的視角，寫出這次對話的核心情緒主題或內心動態。
不要說教或給建議，只描述你觀察到的。直接輸出文字，不加引號或前言。"""

    result = await call_api(prompt, max_tokens=150, tier="haiku")
    return result.strip() if result else ""


async def get_projective_question(card: dict, emotion: str) -> str:
    """
    用 AI（Haiku）依牌面意象生成一句投射式象徵問句。
    問句用後設認知或蘇格拉底視角，讓用戶把自己投射進牌面。
    """
    card_name = card.get("card_name") or card.get("card_full", "")
    meaning   = card.get("meaning", "")
    pos       = "逆位" if card.get("is_reversed") else "正位"

    prompt = f"""你是一位溫柔的塔羅治療師。

用戶現在情緒是「{emotion}」，對話有些停滯。
你為他翻開了【{card_name}・{pos}】，牌義是：「{meaning}」

請生成 1-2 句「投射象徵問句」，幫他把自己的內心狀態投射到牌面意象上。
要求：
- 從牌面畫面中選一個具體意象（不要直接說牌名）
- 用「你覺得…」「此刻的你是…嗎？」或「如果你是畫面中的…」開頭
- 溫柔、非批判、讓人想繼續說下去
- 只輸出問句本身，不要前言或解釋"""

    result = await call_api(prompt, max_tokens=150, tier="haiku")
    return result.strip() if result else f"這張牌的意象，讓你想到了什麼？"


def build_revealed_card_flex(card: dict, question: str) -> dict:
    """
    翻牌後的揭示 Flex Message：牌名 + 正/逆位 + 意義 + AI 投射問句。
    """
    card_name = card.get("card_name") or "？"
    pos       = "逆位" if card.get("is_reversed") else "正位"
    meaning   = card.get("meaning", "")
    mode_label = {"major": "大阿爾克那", "minor": "小阿爾克那", "quote": "名言"}.get(
        card.get("mode", "major"), ""
    )

    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "backgroundColor": "#0f1410",
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "justifyContent": "space-between",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"【{card_name}】",
                            "size": "lg",
                            "color": "#c9a84c",
                            "weight": "bold",
                            "flex": 1,
                        },
                        {
                            "type": "text",
                            "text": pos,
                            "size": "xs",
                            "color": "#6b5d4f",
                            "align": "end",
                            "flex": 0,
                        },
                    ],
                },
                {
                    "type": "text",
                    "text": mode_label,
                    "size": "xxs",
                    "color": "#4a7c59",
                    "letterSpacing": "3px",
                },
                {
                    "type": "separator",
                    "color": "#c9a84c30",
                    "margin": "sm",
                },
                {
                    "type": "text",
                    "text": meaning,
                    "size": "sm",
                    "color": "#a89880",
                    "wrap": True,
                    "lineSpacing": "6px",
                    "margin": "sm",
                },
                {
                    "type": "separator",
                    "color": "#ffffff0d",
                    "margin": "md",
                },
                {
                    "type": "text",
                    "text": question,
                    "size": "sm",
                    "color": "#e8e0d0",
                    "wrap": True,
                    "lineSpacing": "6px",
                },
            ],
        },
    }


# ══════════════════════════════════════════════════════════
# 3. 收尾字卡 Flex（今日日記封存）
# ══════════════════════════════════════════════════════════

def build_closure_flex(
    quote_text: str,
    is_tarot: bool,
    card_name: str = None,
    quote_author: str = None,
    dialogue_insight: str = None,
    insight_id: int = None,
) -> dict:
    """
    對話收尾的 Flex Message 字卡。
    結構：🌙 封存標題 ＋ AI 洞察 ＋ 哲人名言 ＋ 覆蓋塔羅翻牌 ＋ 查看日記按鈕。

    當 insight_id 提供時，塔羅牌以「覆蓋」狀態呈現，點擊觸發翻牌 Postback。
    未提供時降級為純文字名言卡（相容舊流程）。
    """
    import datetime as _dt
    _today = _dt.date.today()
    today_str = f"{_today.month} 月 {_today.day} 日"

    author_line = f"—— {quote_author}" if quote_author else ""

    body_contents: list[dict] = [
        # ── Header ──────────────────────────────────────────────
        {
            "type": "box",
            "layout": "horizontal",
            "justifyContent": "space-between",
            "alignItems": "center",
            "contents": [
                {
                    "type": "text",
                    "text": "🌙 今日日記已封存",
                    "size": "sm",
                    "color": "#c9a84c",
                    "weight": "bold",
                    "flex": 1,
                },
                {
                    "type": "text",
                    "text": today_str,
                    "size": "xxs",
                    "color": "#6b5d4f",
                    "flex": 0,
                    "align": "end",
                },
            ],
        },
        {
            "type": "text",
            "text": "謝謝你今天願意對我說說心裡的話。",
            "size": "xs",
            "color": "#6b5d4f",
            "wrap": True,
            "margin": "sm",
        },
    ]

    # ── AI 對話洞察 ─────────────────────────────────────────
    if dialogue_insight:
        body_contents += [
            {"type": "separator", "color": "#ffffff0d", "margin": "lg"},
            {
                "type": "text",
                "text": "TODAY'S MIRROR",
                "size": "xxs",
                "color": "#4a7c59",
                "letterSpacing": "3px",
                "margin": "lg",
            },
            {
                "type": "text",
                "text": dialogue_insight,
                "size": "sm",
                "color": "#a89880",
                "wrap": True,
                "lineSpacing": "6px",
                "margin": "xs",
            },
        ]

    # ── 哲人名言 ────────────────────────────────────────────
    body_contents += [
        {"type": "separator", "color": "#c9a84c30", "margin": "lg"},
        {
            "type": "text",
            "text": "WISDOM",
            "size": "xxs",
            "color": "#4a7c59",
            "letterSpacing": "3px",
            "margin": "lg",
        },
        {
            "type": "text",
            "text": f"「{quote_text}」",
            "size": "sm",
            "color": "#e8e0d0",
            "wrap": True,
            "lineSpacing": "8px",
            "style": "italic",
            "margin": "xs",
        },
    ]
    if author_line:
        body_contents.append({
            "type": "text",
            "text": author_line,
            "size": "xxs",
            "color": "#6b5d4f",
            "align": "end",
            "margin": "xs",
        })

    # ── 塔羅（覆蓋牌 + 翻牌按鈕 / 降級純文字）────────────────
    if insight_id:
        body_contents += [
            {"type": "separator", "color": "#c9a84c30", "margin": "lg"},
            {
                "type": "text",
                "text": "TODAY'S CARD",
                "size": "xxs",
                "color": "#4a7c59",
                "letterSpacing": "3px",
                "margin": "lg",
            },
            {
                "type": "text",
                "text": "今日一張引導牌正在等待你翻開。",
                "size": "xs",
                "color": "#6b5d4f",
                "wrap": True,
                "margin": "xs",
            },
            {
                # 覆蓋牌圖示區域
                "type": "box",
                "layout": "vertical",
                "height": "100px",
                "justifyContent": "center",
                "alignItems": "center",
                "backgroundColor": "#161c18",
                "cornerRadius": "10px",
                "borderWidth": "1px",
                "borderColor": "#c9a84c40",
                "margin": "md",
                "contents": [
                    {
                        "type": "text",
                        "text": "🎴",
                        "size": "3xl",
                        "align": "center",
                    },
                    {
                        "type": "text",
                        "text": "點我翻牌",
                        "size": "xxs",
                        "color": "#c9a84c",
                        "align": "center",
                        "margin": "sm",
                        "letterSpacing": "2px",
                    },
                ],
                "action": {
                    "type": "postback",
                    "label": "翻開今日引導牌",
                    "data": f"action=flip_tarot&insight_id={insight_id}",
                    "displayText": "（翻開今日引導牌 🃏）",
                },
            },
        ]
    elif is_tarot and card_name:
        # 降級：直接顯示牌名（insight_id 不可用時）
        body_contents += [
            {"type": "separator", "color": "#c9a84c30", "margin": "lg"},
            {
                "type": "text",
                "text": f"【{card_name}】",
                "size": "xs",
                "color": "#c9a84c",
                "letterSpacing": "2px",
                "margin": "lg",
            },
        ]

    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "none",
            "backgroundColor": "#0f1410",
            "paddingAll": "20px",
            "contents": body_contents,
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "backgroundColor": "#0f1410",
            "paddingAll": "12px",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "查看我的心事本",
                        "uri": f"{LIFF_URL}#dashboard",
                    },
                    "style": "primary",
                    "color": "#4a7c59",
                    "height": "sm",
                },
            ],
        },
    }


def build_closure_revealed_flex(
    card_name: str, orientation: str, tarot_insight: str
) -> dict:
    """
    翻牌後顯示的揭示卡片（收尾專用，與 STAGNANT 翻牌的 build_revealed_card_flex 獨立）。
    """
    pos = "逆位" if orientation == "REVERSED" else "正位"
    return {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "backgroundColor": "#0f1410",
            "paddingAll": "20px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "justifyContent": "space-between",
                    "alignItems": "center",
                    "contents": [
                        {
                            "type": "text",
                            "text": f"【{card_name}】",
                            "size": "lg",
                            "color": "#c9a84c",
                            "weight": "bold",
                            "flex": 1,
                        },
                        {
                            "type": "text",
                            "text": pos,
                            "size": "xs",
                            "color": "#6b5d4f",
                            "align": "end",
                            "flex": 0,
                        },
                    ],
                },
                {"type": "separator", "color": "#c9a84c30", "margin": "md"},
                {
                    "type": "text",
                    "text": tarot_insight,
                    "size": "sm",
                    "color": "#a89880",
                    "wrap": True,
                    "lineSpacing": "7px",
                    "margin": "sm",
                },
                {"type": "separator", "color": "#ffffff0d", "margin": "lg"},
                {
                    "type": "text",
                    "text": "把這張牌的意象帶在心裡。\n隨時想說更多，我在。",
                    "size": "xs",
                    "color": "#6b5d4f",
                    "wrap": True,
                    "lineSpacing": "5px",
                    "margin": "sm",
                },
            ],
        },
    }
