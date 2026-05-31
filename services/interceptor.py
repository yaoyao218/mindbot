"""
P0 Pydantic 攔截器
過濾說教語句、截斷多問句
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

# 說教語句的替換方式：移除該句子
_PREACHY_RE = re.compile(
    r"[^。！？…]*(?:" + "|".join(PREACHY_PATTERNS) + r")[^。！？…]*[。！？…]?",
    re.UNICODE
)


def filter_preachy(text: str) -> str:
    """移除說教語句"""
    cleaned = _PREACHY_RE.sub("", text).strip()
    # 去除多餘的空行
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned if cleaned else text  # 若全部被過濾則保留原文


def truncate_to_first_question(text: str) -> str:
    """
    多問句截斷：超過一個問號 → 只保留第一問（含其前置脈絡）
    """
    # 找所有問號位置
    question_positions = [i for i, c in enumerate(text) if c in "？?"]

    if len(question_positions) <= 1:
        return text

    # 只保留第一個問號之前的內容（含問號）
    first_q_pos = question_positions[0]
    return text[:first_q_pos + 1].strip()


def process_response(
    raw_response: str,
    fast_path_result: Optional[FastPathResult] = None
) -> str:
    """
    完整攔截器流程：
    1. 過濾說教語句
    2. 截斷多問句
    3. 字數截斷（依 FastPathResult）
    """
    result = raw_response

    # Step 1: 說教語句過濾
    result = filter_preachy(result)

    # Step 2: 多問句截斷
    result = truncate_to_first_question(result)

    # Step 3: 字數截斷
    if fast_path_result and fast_path_result.max_bot_length:
        result = truncate_bot_reply(result, fast_path_result.max_bot_length)

    return result.strip()
