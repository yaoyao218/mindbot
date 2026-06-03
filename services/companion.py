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


async def get_reply(session: dict, user_text: str) -> tuple[str, dict]:
    """
    主對話入口
    回傳 (reply_text, session_updates)
    """
    history = session.get("history", [])
    history_str = _format_history(history)

    prompt = COMPANION_PROMPT_TEMPLATE.format(
        conversation_history=history_str,
        user_message=user_text,
    )

    reply = await call_api(
        prompt=prompt,
        system=COMPANION_SYSTEM,
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
