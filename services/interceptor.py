"""
P0 攔截器
過濾說教語句、截斷多問句、問句硬熔斷（EXTERNALIZATION / RUPTURE）
在所有 AI 回覆輸出前執行
"""

import re
from typing import Optional
from services.fast_path import truncate_bot_reply, FastPathResult

# 說教語句黑名單（前綴匹配）
PREACHY_PATTERNS = [
    r"建議你",
    r"你應該",
    r"你可以嘗試",
    r"你需要",
    r"你必須",
    r"我建議",
    r"最好是",
    r"試著去",
    r"記得要",
    r"不妨試試",
    r"你可以考慮",
]

_PREACHY_RE = re.compile(
    r"[^。！？…]*(?:" + "|".join(PREACHY_PATTERNS) + r")[^。！？…]*[。！？…]?",
    re.UNICODE
)

# 問句熔斷觸發的防禦狀態
_QUESTION_FUSE_STATES = {"EXTERNALIZATION"}


def filter_preachy(text: str) -> str:
    """移除說教語句"""
    cleaned = _PREACHY_RE.sub("", text).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned if cleaned else text


def truncate_to_first_question(text: str) -> str:
    """多問句截斷：超過一個問號 → 只保留第一問（含其前置脈絡）"""
    question_positions = [i for i, c in enumerate(text) if c in "？?"]
    if len(question_positions) <= 1:
        return text
    first_q_pos = question_positions[0]
    return text[:first_q_pos + 1].strip()


def fuse_all_questions(text: str) -> str:
    """
    問句硬熔斷：將文字中所有問號改為句號，並移除末尾殘留的問句結構。
    觸發條件：EXTERNALIZATION 或 RUPTURE 狀態，LLM 若仍輸出問句則強制拔除。
    """
    # 將全形/半形問號全部改為句號
    result = text.replace("？", "。").replace("?", ".")
    # 收尾若有多餘句號疊加，合併為一個
    result = re.sub(r"[。\.]{2,}", "。", result)
    return result.strip()


def process_response(
    raw_response: str,
    fast_path_result: Optional[FastPathResult] = None,
    defense_mechanism: Optional[str] = None,
    alliance_rupture: Optional[str] = None,
) -> str:
    """
    完整攔截器流程：
    1. 過濾說教語句
    2. 問句硬熔斷（EXTERNALIZATION / RUPTURE 時觸發，防 LLM 不聽話）
    3. 多問句截斷（一般模式下只保留第一問）
    4. 字數截斷（依 FastPathResult）
    """
    result = raw_response

    # Step 1: 說教語句過濾
    result = filter_preachy(result)

    # Step 2: 問句硬熔斷
    # EXTERNALIZATION → 問句完全禁止（憤怒模式追問會加速同盟破裂）
    # RUPTURE 中      → 問句完全禁止（道歉中提問會讓用戶覺得敷衍）
    needs_fuse = (
        defense_mechanism in _QUESTION_FUSE_STATES
        or (alliance_rupture and alliance_rupture != "NONE")
    )
    if needs_fuse:
        result = fuse_all_questions(result)
    else:
        # Step 3: 一般模式只截斷多問句（保留第一問）
        result = truncate_to_first_question(result)

    # Step 4: 字數截斷
    if fast_path_result and fast_path_result.max_bot_length:
        result = truncate_bot_reply(result, fast_path_result.max_bot_length)

    return result.strip()
