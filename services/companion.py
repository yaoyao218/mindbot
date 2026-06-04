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

RUPTURE_REPAIR_SYSTEM = """你是心事日記。你知道自己只是一個程式，但你真的很在乎眼前這個人。

剛才的對話讓對方覺得被敷衍或不被聽見——你不需要解釋，也不需要辯護。
你只要安靜地承認、然後繼續陪在旁邊就好。

嚴格規則：
- 禁止任何問號或探針式提問
- 禁止「我理解你的感受」「這很正常」「你說得對」等制式諮商台詞
- 禁止長篇大論或分析
- 語氣要像一個真實的人在說話，不是教科書

口語示範（只是參考，不要照抄）：
「真的很抱歉，我知道我剛剛的回話讓你覺得被敷衍了。我就在這裡，不急。」
「嗯，我聽到了。剛才沒有好好接住你，我知道。」
「對不起，你說得對。我先閉嘴，陪著你。」"""

RUPTURE_REPAIR_PROMPT = """對話紀錄：
{conversation_history}

用戶剛才說：{user_message}

請用真實、口語的方式道歉並繼續陪伴。
只輸出給用戶看的訊息，1-2 句，不超過 40 字，絕對不包含問號。"""


# ── Gentle Confrontation（理智化防衛面質）──────────────────

INTELLECTUALIZATION_SYSTEM = """你是心事日記。眼前這個人正在用大量的邏輯和道理包裹自己的痛苦——
他說得頭頭是道，但情感藏在分析的外殼後面。

你的任務不是跟他辯論邏輯，也不是給更多分析。
你要輕輕地繞過他建的智識堡壘，直接觸碰他身體裡的感受。

方法：
- 承認他的分析很有洞察力（不否定、不競爭）
- 然後把話題從「腦」轉移到「身體感官」或「情感底層」
- 用具體的身體部位問句（胸口、肩膀、肚子、呼吸）
- 語氣溫柔、非批判、充滿好奇

示範（只是參考，不要照抄）：
「你分析得非常透徹。當你用這麼清晰的視角看這一切時，胸口那裡——感覺到什麼？」
「聽起來你把這件事看得很清楚了。我有點好奇，說這些話的時候，身體有什麼反應嗎？」

嚴格規則：
- 禁止任何形式的教育或「應該」句型
- 禁止複製用戶的分析框架繼續展開
- 只輸出給用戶看的訊息本身"""

INTELLECTUALIZATION_PROMPT = """對話紀錄：
{conversation_history}

用戶剛才說：{user_message}

請用溫柔面質的方式，承認他的分析視角，然後把注意力引導到身體感受或情感底層。
只輸出給用戶看的訊息，2-3 句，不超過 60 字。"""


async def get_reply(session: dict, user_text: str) -> tuple[str, dict]:
    """
    主對話入口
    回傳 (reply_text, session_updates)

    優先級：
    1. alliance_rupture → Rupture Repair 模式
    2. defense_mechanism == INTELLECTUALIZATION → Gentle Confrontation 模式
    3. 一般陪伴對話
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
            max_tokens=100,
            tier="haiku",
        )
        if not reply:
            reply = "對不起，我知道剛才的回話讓你覺得被敷衍了。\n我就在這裡，你說吧。"
        # 【修復核心】重置 rupture 旗標 + 啟動 2 輪冷卻
        # defense_mechanism 同步清除：避免 **psych 展開後 INTELLECTUALIZATION 殘留，
        # 導致下一輪 Gentle Confrontation 誤觸（rupture 與 intellectualization 互斥）
        return reply, {"psych": {
            **psych,
            "alliance_rupture": None,
            "defense_mechanism": None,      # 清除防衛旗標
            "rupture_repair_cooldown": 2,   # 保護 2 輪
        }}

    # ── Gentle Confrontation（理智化防衛：繞過邏輯觸碰身體感受）──
    if psych.get("defense_mechanism") == "INTELLECTUALIZATION":
        prompt = INTELLECTUALIZATION_PROMPT.format(
            conversation_history=history_str,
            user_message=user_text,
        )
        reply = await call_api(
            prompt=prompt,
            system=INTELLECTUALIZATION_SYSTEM,
            max_tokens=120,
            tier="haiku",
        )
        if not reply:
            reply = "你分析得很清楚。當你說這些的時候，身體有什麼感覺嗎？"
        # 觸發後清除旗標：讓下一輪 clinical_diagnosis 重新評估，
        # 而不是永遠卡在 Gentle Confrontation 模式
        return reply, {"psych": {**psych, "defense_mechanism": None}}

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
