"""
P0 Fast-Path 靜態評估器
微秒級評估，不走 AI，在所有 AI 呼叫之前執行
"""

from dataclasses import dataclass
from typing import Optional

# 危機關鍵字
CRISIS_KEYWORDS = [
    "不想活", "想死", "自殺", "去死", "活不下去",
    "結束生命", "消失算了", "死了算了", "不如死",
    "輕生", "了結", "跳樓", "割腕"
]

# 情感阻斷詞（≤5 字 + 這些詞 → 阻滯狀態）
BLOCK_WORDS = [
    "不知道", "算了", "沒事", "無所謂", "隨便",
    "管他", "不重要", "算了吧", "沒關係", "沒用"
]


@dataclass
class FastPathResult:
    is_crisis: bool = False
    is_high_arousal: bool = False   # 字數 ≥ 150
    is_blocked: bool = False        # 情感阻滯
    max_bot_chars: Optional[int] = None  # None 表示不限制
    user_char_count: int = 0


def evaluate(user_text: str) -> FastPathResult:
    """
    靜態快速評估，回傳 FastPathResult
    """
    text = user_text.strip()
    char_count = len(text)
    result = FastPathResult(user_char_count=char_count)

    # 1. 危機關鍵字
    for kw in CRISIS_KEYWORDS:
        if kw in text:
            result.is_crisis = True
            return result  # 危機立刻返回，不繼續評估

    # 2. 高波動（字數 ≥ 150）
    if char_count >= 150:
        result.is_high_arousal = True
        # Bot 最多回 40% 輸入字數，最少 60 字
        result.max_bot_chars = max(60, int(char_count * 0.4))

    # 3. 情感阻滯（≤5 字 + 阻斷詞）
    if char_count <= 5:
        for bw in BLOCK_WORDS:
            if bw in text:
                result.is_blocked = True
                result.max_bot_chars = 80
                break

    return result


def truncate_response(text: str, max_chars: Optional[int]) -> str:
    """依 Fast-Path 結果截斷 Bot 回覆"""
    if max_chars is None or len(text) <= max_chars:
        return text

    # 截斷到最近的句子結尾
    truncated = text[:max_chars]
    for punct in ["。", "？", "！", "…"]:
        idx = truncated.rfind(punct)
        if idx > max_chars * 0.6:
            return truncated[:idx + 1]

    return truncated
