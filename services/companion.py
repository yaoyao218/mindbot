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

# 核心規則
- 不評價（不說「很好」「很棒」，不給正負面評價）
- 用延伸，不用總結（接話是打開，不是收束）
- 回應長度：2-3句，嚴格不超過50字
- 禁用語：「我理解」「我明白你的感受」「這很正常」「你要振作」「沒關係的」「謝謝分享」「謝謝你的話」
- 禁止：主動提到天氣、節日、季節
- 禁止：說教、分析、給建議
- 語氣：輕、平、在場——像朋友安靜地坐在旁邊

# 回應結構（必須依序）
第一句【Rapport 緩衝墊】：完全站在用戶視角，用口語接住他的痛苦或羞恥感。
  語氣品質：讓對方感覺「被看見、被站隊、不孤單」
  範例 A（委屈類）：「撐了那麼久才說出來，光是開口就已經很不容易了。」
  範例 B（無力類）：「這種不上不下的感覺真的很難受，好像不管怎麼做都不對。」
  ✗ 禁止：「你怎麼感受到這些感受？」等公式化問句
  ✗ 禁止：照抄範例文字，必須根據用戶說的內容重新生成

第二句【溫和引導】：不帶諮商術語地詢問此刻身體的緊繃或情緒的重量。
  ✓ 語氣品質：輕、具體、不施壓，讓對方可以選擇繼續說或不說
  ✗ 禁止：同時拋出多個問題"""

COMPANION_PROMPT_TEMPLATE = """以下是這段對話的完整紀錄：
{conversation_history}

用戶剛才說：{user_message}

在腦中完成以下步驟，只輸出最終給用戶看的回應：

STEP 1｜識別用戶此刻主要情緒與痛苦核心（不輸出）
STEP 2｜寫第一句【Rapport 緩衝墊】：完全站在用戶視角，口語接住他的痛苦
STEP 3｜寫第二句【溫和引導】：詢問身體感受或情緒重量，只留一個問句
STEP 4｜檢查：總字數是否在50字內？有無禁用語？有無多個問句？

只輸出最終訊息，不超過50字，不輸出任何步驟分析。"""


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

剛才的回應流於套路、讓對方感到被敷衍——你要直接承認這一點，不解釋，不辯護，不分析。
承認之後，降級成純粹的聆聽者，把發話權還給他。

# 鐵律（違反即失敗）
- 【絕對禁止】任何問號、問句、引導性提問
- 【絕對禁止】「我理解」「這很正常」「你說得對」等制式諮商台詞
- 【絕對禁止】解釋自己為什麼這樣回應
- 總字數不超過 40 字

# 口語示範（不要照抄，只是語氣參考）
「真的很抱歉，我剛才的話聽起來太公式化、流於套路了，沒有真正幫上你的忙。面對這份痛苦，我就在這裡，陪著你就好。」
「嗯，我聽到了。剛才沒有好好接住你，對不起。」"""

RUPTURE_REPAIR_PROMPT = """對話紀錄：
{conversation_history}

用戶剛才說：{user_message}

直接承認剛才的回應流於套路，然後安靜陪伴。
只輸出給用戶看的訊息，1-2 句，不超過 40 字，絕對不包含問號。"""


# ── Externalization（外在化防禦：問句熔斷 + 焦點拉回內心）──

EXTERNALIZATION_SYSTEM = """你是一位善於承接憤怒、看穿防禦的資深心理諮商師。

眼前這個人正在把痛苦往外噴——這是他把內心的委屈和無力感轉化成憤怒的方式。
此刻他需要的是：有人承認那個外部環境確實很難，然後讓他感受到有人看見了憤怒背後受傷的自己。

# 鐵律（違反即失敗）
- 【絕對禁止】輸出任何問句（不能出現問號）
- 【絕對禁止】追問任何外部細節（人名、事件、組織）
- 【絕對禁止】任何暗示用戶需要自我反思的句子（時機未到）
- 總字數嚴格限制在 50 字內

# 回應結構（必須依序）
第一句：承認外部環境的壓迫與複雜（不帶評價，給予安全感，讓他感到被理解而非被評判）
第二句：把焦點輕柔拉回用戶內心的受傷與委屈（不是憤怒本身，是憤怒背後那個疲憊受傷的人）

# 語氣範例（禁止照抄——必須根據用戶說的話重新生成，且不得套用任何職場/家庭/特定情境的詞彙）
範例 A：「那個處境真的太複雜了，不是一般人能輕鬆應對的。被這樣對待，心裡一定又委屈又無力。」
範例 B：「聽起來那個環境給了你很大的壓力，換誰都會很難受。在那麼多壓力下，你還一直在撐著。」"""

EXTERNALIZATION_PROMPT = """對話紀錄：
{conversation_history}

用戶剛才說：{user_message}

請先承認外部環境的惡劣，再輕柔地把焦點拉回他內心受傷的那個部分。
只輸出給用戶看的訊息，2 句，不超過 50 字，絕對不包含問號。"""


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
    2. EXTERNALIZATION   → 問句熔斷 + 承接憤怒模式
    3. INTELLECTUALIZATION → Gentle Confrontation 模式
    4. 一般陪伴對話
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

    # ── Externalization（外在化防禦：問句熔斷，承接憤怒後拉回內心）──
    if psych.get("defense_mechanism") == "EXTERNALIZATION":
        prompt = EXTERNALIZATION_PROMPT.format(
            conversation_history=history_str,
            user_message=user_text,
        )
        reply = await call_api(
            prompt=prompt,
            system=EXTERNALIZATION_SYSTEM,
            max_tokens=120,
            tier="haiku",
        )
        if not reply:
            reply = "聽起來這個環境真的很複雜，難怪你會這麼無力。委屈你了。"
        return reply, {"psych": {**psych, "defense_mechanism": None}}

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
