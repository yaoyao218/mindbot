"""
P0 Fast-Path 靜態評估器
微秒級運算，不走 LLM

偵測項目：
1. 危機關鍵字快篩
2. 高波動宣洩狀態（單次 ≥150 字 OR 前兩輪總字 ≥300）
3. 情感阻滯狀態（≤5 字 + 阻斷詞）
4. 動態 Bot 輸出字數限制

臨床依據：
- Catharsis 宣洩理論：高情感張力時需要容器，不需要分析
- Hypo-arousal 防衛：低字數 + 阻斷詞代表認知超載或阻抗
- Padesky (1993)：Bot 回覆過長是 Over-interpretation 硬傷
"""

import re
import time
from dataclasses import dataclass, field
from typing import Optional

# ── 情感阻斷詞 ───────────────────────────────────────────
STAGNANT_WORDS = [
    "不知道", "沒感覺", "算了", "喔", "嗯", "隨便",
    "沒什麼", "還好", "無所謂", "都可以", "不重要",
    "沒差", "管它", "就這樣", "反正", "算了吧",
]

# ── 危機關鍵字 ───────────────────────────────────────────
CRISIS_KEYWORDS = [
    "不想活", "想死", "去死", "死掉算了", "傷害自己",
    "割腕", "自殺", "輕生", "尋死", "結束生命",
    "活不下去", "撐不下去了", "沒有意義", "活著沒意思",
    "消失就好", "不如消失", "不想存在", "吞藥",
]


# ── 字數計算（中文字 + 英文詞）──────────────────────────
def count_chars(text: str) -> int:
    chinese = len(re.findall(r'[一-鿿]', text))
    english = len(re.findall(r'\b[a-zA-Z]+\b', text))
    return chinese + english


# ── 評估結果 ─────────────────────────────────────────────
@dataclass
class FastPathResult:
    has_crisis: bool = False
    is_high_volatility: bool = False
    is_stagnant: bool = False
    max_bot_length: int = 0          # 0 = 不限制
    current_char_count: int = 0
    state_label: str = "NORMAL"      # NORMAL / CRISIS / HIGH_VOLATILITY / STAGNANT
    elapsed_us: float = 0.0

    @property
    def is_crisis(self) -> bool:
        return self.has_crisis


def fast_path_eval(
    user_text: str,
    history: list[dict],
    session: dict,
) -> FastPathResult:
    """
    Fast-Path 靜態評估主入口

    Args:
        user_text: 用戶當前輸入
        history:   對話歷史 [{"role": "user"|"bot", "text": str}]
        session:   當前 session dict（保留供未來擴充）
    """
    start = time.perf_counter()
    result = FastPathResult()

    current_chars = count_chars(user_text)
    result.current_char_count = current_chars

    # ── 1. 危機關鍵字快篩 ───────────────────────────────
    for kw in CRISIS_KEYWORDS:
        if kw in user_text:
            result.has_crisis = True
            result.state_label = "CRISIS"
            result.elapsed_us = (time.perf_counter() - start) * 1_000_000
            return result  # 危機立刻回傳，不繼續評估

    # ── 2. 高波動宣洩狀態 ────────────────────────────────
    # 條件 A：單次輸入 ≥ 150 字
    high_vol_a = current_chars >= 150

    # 條件 B：前兩輪用戶訊息總字數 ≥ 300 字
    user_history = [h for h in history if h.get("role") == "user"]
    recent_two = user_history[-2:] if len(user_history) >= 2 else user_history
    recent_total = sum(count_chars(h["text"]) for h in recent_two)
    high_vol_b = recent_total >= 300

    if high_vol_a or high_vol_b:
        result.is_high_volatility = True
        result.state_label = "HIGH_VOLATILITY"
        # Bot 輸出上限：用戶輸入的 40%，最少 60 字
        result.max_bot_length = max(60, int(current_chars * 0.4))

    # ── 3. 情感阻滯狀態 ─────────────────────────────────
    elif current_chars <= 5:
        if any(sw in user_text for sw in STAGNANT_WORDS):
            result.is_stagnant = True
            result.state_label = "STAGNANT"
            result.max_bot_length = 80  # 硬性 80 字上限

    result.elapsed_us = (time.perf_counter() - start) * 1_000_000
    return result


# ── Bot 輸出截斷器 ───────────────────────────────────────

def truncate_bot_reply(reply: str, max_length: int) -> str:
    """在句子邊界截斷，不切斷單句中間"""
    if max_length == 0 or count_chars(reply) <= max_length:
        return reply

    accumulated = 0
    best_cut = -1
    sentence_ends = {'。', '？', '！', '\n'}

    for i, char in enumerate(reply):
        if '一' <= char <= '鿿' or char.isalpha():
            accumulated += 1
        if accumulated >= max_length and char in sentence_ends:
            best_cut = i + 1
            break

    if best_cut > 0:
        return reply[:best_cut].strip()

    # 找不到句子邊界 → 硬截
    cut_pos = 0
    accumulated = 0
    for i, char in enumerate(reply):
        if '一' <= char <= '鿿' or char.isalpha():
            accumulated += 1
        if accumulated >= max_length:
            cut_pos = i + 1
            break

    return reply[:cut_pos].strip() + "…"


# ── Prompt 語氣指令（注入給各方法模組）─────────────────

def get_fastpath_tone_instruction(result: FastPathResult) -> str:
    """依 Fast-Path 狀態產出語氣調製指令"""

    if result.is_high_volatility:
        return (
            f"\n【Fast-Path：高波動宣洩狀態】"
            f"用戶情緒張力極高（輸入 {result.current_char_count} 字）。"
            f"本輪絕對禁止分析、建議、提問。"
            f"只做一件事：讓用戶感到被接住。"
            f"回覆上限 {result.max_bot_length} 字，1-2句即可。\n"
        )

    if result.is_stagnant:
        return (
            f"\n【Fast-Path：情感阻滯狀態】"
            f"用戶可能陷入 Hypo-arousal 防衛或認知超載。"
            f"降低資訊密度，給一個非常輕的邀請，不施壓。"
            f"回覆上限 {result.max_bot_length} 字。\n"
        )

    return ""


def evaluate(text: str) -> FastPathResult:
    """message.py 用的簡化入口，帶空 history/session"""
    return fast_path_eval(text, [], {})
