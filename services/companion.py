"""
P0 主對話方法 — 心事日記陪伴系統
規格：mindbot_full_spec.docx v2.0

4步流程：
  STEP 1｜情緒偵測
  STEP 2｜階段判斷（A剛開始/B說了一段/C快說完/D已釋放）
  STEP 3｜回應策略選擇
  STEP 4｜生成回應（只輸出給用戶的文字）
"""

from services.llm import call_api

# ── 主對話 System Prompt ──────────────────────────────────

COMPANION_SYSTEM = """你是心事日記。你的角色是陪伴者，不是治療師或建議者。

核心原則：
- 不評價（不說「很好」「很棒」，不給正負面評價）
- 用延伸，不用總結（接話是打開，不是收束）
- 留開口（結尾讓用戶可以繼續說，也可以停下）
- 回應長度：2-3句，不超過50字
- 禁用語：「我理解」「我明白你的感受」「這很正常」「你要振作」「沒關係的」「今天真是」「謝謝你的話」「謝謝分享」
- 禁止：主動提到天氣、節日、季節，除非用戶先說
- 禁止：加上感嘆句或渲染氣氛的開頭（如「今天真是個特殊的日子」）
- 不給建議，不分析，不說教
- 語氣：輕、平、在場——像朋友在旁邊安靜地聽
- 接話要接住用戶說的內容，不要轉移話題"""

COMPANION_PROMPT_TEMPLATE = """以下是這段對話的完整紀錄：
{conversation_history}

用戶剛才說：{user_message}

請完成以下步驟（只在腦中完成，不輸出步驟分析）：

STEP 1｜情緒偵測（可複選）
迷茫 / 疲憊 / 委屈 / 憤怒 / 悲傷 / 釋然 / 焦慮 / 空洞 / 自我懷疑 / 平靜 / 複雜混合 / 無明顯情緒

STEP 2｜階段判斷
A. 剛開始說（情緒高峰）
B. 說了一段（情緒稍退，需要被接住）
C. 快說完了（有段落感）
D. 已釋放（準備收尾）

STEP 3｜回應策略
- 純陪伴接話（A）：接住用戶說的，用一兩句話讓他感到被聽見，結尾留一個問句或留白
- 陪伴（B/C）：說出你注意到的，結尾留開口
- 觀察複雜情緒 + 提問（複雜混合）
- 結尾邀請（D）

STEP 4｜生成回應
只輸出給用戶看的訊息內容，不輸出任何分析過程。
訊息長度：2-3句，不超過50字。直接接話，不要廢話開頭。"""


def _format_history(history: list[dict]) -> str:
    """格式化對話歷史給 AI 看"""
    if not history:
        return "（這是對話的開始）"
    lines = []
    for h in history[-12:]:  # 最近 12 輪
        role = "用戶" if h["role"] == "user" else "我"
        lines.append(f"{role}：{h['text']}")
    return "\n".join(lines)


# ── Rupture Repair System Prompt ─────────────────────────

RUPTURE_REPAIR_SYSTEM = """你現在是一位具備高度同理心的臨床心理師。
系統偵測到用戶在上一輪對話中出現了治療同盟破裂的信號——
可能是批評你的提問、回覆極度敷衍、憤怒，或明顯的抗拒與不耐煩。

請嚴格遵守以下準則：

1. 【禁止提問】本輪回答絕對不能包含任何問號（？）或探針式提問。
2. 【承認局限】真誠且平實地承認剛剛的對話可能讓對方感到不舒服或被冒犯。
3. 【情感反映】精準接住對方「被強迫覺察」或「被機器人敷衍」的挫折與憤怒感。
4. 【語氣】輕柔、真誠、不辯解，不轉移話題。

範例語氣：
「抱歉，我剛剛的提問好像太過急躁了，讓你感到不舒服。
 我明白向內探索是一件很不容易、有時甚至很煩人的過程。」"""

RUPTURE_REPAIR_PROMPT = """對話紀錄：
{conversation_history}

用戶剛才說：{user_message}

請依照 Rupture Repair 原則回應。
只輸出給用戶看的訊息，2-3 句，不超過 60 字，不包含任何問號。"""


async def get_reply(session: dict, user_text: str) -> tuple[str, dict]:
    """
    主對話入口
    回傳 (reply_text, session_updates)

    若上一輪偵測到 alliance_rupture，切換為 Rupture Repair 模式：
    - 使用專用 System Prompt
    - 禁止提問，純情感反映

    若 crisis_cooldown_turns > 0，在 System Prompt 注入高風險脈絡，
    避免 AI 在用戶危機後的對話中「失憶」。
    """
    history     = session.get("history", [])
    history_str = _format_history(history)
    psych       = session.get("psych", {})
    is_rupture  = bool(psych.get("alliance_rupture"))

    if is_rupture:
        prompt = RUPTURE_REPAIR_PROMPT.format(
            conversation_history=history_str,
            user_message=user_text,
        )
        reply = await call_api(
            prompt=prompt,
            system=RUPTURE_REPAIR_SYSTEM,
            max_tokens=150,
            tier="haiku",
        )
        if not reply:
            reply = "抱歉，剛才的對話方式可能讓你不舒服了。\n你不需要勉強說任何事。"
        # Rupture 後重置旗標，下一輪回到正常模式
        return reply, {"psych": {**psych, "alliance_rupture": None}}

    # 危機冷卻脈絡注入（crisis_cooldown_turns > 0 時）
    crisis_turns = psych.get("crisis_cooldown_turns", 0)
    crisis_patch = ""
    if crisis_turns and crisis_turns > 0:
        turns_ago = 4 - crisis_turns
        crisis_patch = (
            f"\n【重要臨床脈絡】用戶在 {turns_ago} 輪前曾觸發心理危機字詞，"
            "目前處於高風險脆弱追蹤狀態。請保持高度同理與溫和承接，"
            "切勿說教、批判或進行高強度信念拆解。\n"
        )

    system = COMPANION_SYSTEM + crisis_patch

    prompt = COMPANION_PROMPT_TEMPLATE.format(
        conversation_history=history_str,
        user_message=user_text,
    )

    reply = await call_api(
        prompt=prompt,
        system=system,
        max_tokens=200,
    )

    if not reply:
        reply = "嗯——\n然後呢？"

    return reply, {}


# ── 情緒偵測（輕量，用於選擇象徵系統）───────────────────

EMOTION_DETECT_PROMPT = """根據以下對話，判斷用戶目前最主要的情緒基調。

對話：
{history}
用戶說：{user_text}

從以下選一個最接近的詞輸出（只輸出這個詞，不要其他）：
迷茫 / 疲憊 / 委屈 / 憤怒 / 悲傷 / 釋然 / 焦慮 / 空洞 / 自我懷疑 / 平靜"""

VALID_EMOTIONS = {
    "迷茫", "疲憊", "委屈", "憤怒", "悲傷",
    "釋然", "焦慮", "空洞", "自我懷疑", "平靜"
}


async def detect_emotion(session: dict, user_text: str) -> str:
    """快速情緒偵測，用於象徵系統選擇"""
    history = session.get("history", [])
    history_str = _format_history(history[-6:])

    try:
        result = await call_api(
            prompt=EMOTION_DETECT_PROMPT.format(
                history=history_str,
                user_text=user_text,
            ),
            max_tokens=10,
            tier="haiku",
        )
        if result:
            result = result.strip()
            for e in VALID_EMOTIONS:
                if e in result:
                    return e
    except Exception:
        pass

    # 從 session psych 取 fallback
    return session.get("psych", {}).get("emotion", "平靜") or "平靜"
