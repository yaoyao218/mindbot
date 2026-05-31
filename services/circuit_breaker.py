"""
P2 增強版 Circuit Breaker + 漸進式轉介阻尼器

Circuit Breaker（三態狀態機）：
  CLOSED  → 正常運作
  OPEN    → 連續 3 次 API 失敗，切靜態兜底
  HALF_OPEN → 冷卻後嘗試恢復，2 次成功才回 CLOSED

轉介阻尼器（ReferralDampener）：
  次數記錄存 DB（重啟不歸零）
  Arousal 5 → 強制插入 1925 危機資源
  Arousal 4 → 強烈建議諮商
  Arousal 1 → 溫柔說明麻木狀態
  Arousal 2-3 → 每日最多 3 次去標籤化推廣
"""

import time
import random
import os
import httpx

# ── 靜態兜底語句池 ───────────────────────────────────────

FALLBACK_POOL = {
    5: ["我還在這裡。你不是一個人。",
        "我聽到你了，現在不需要說任何話。",
        "你願意開口，這本身就需要很大的勇氣。"],
    4: ["我聽到你說的了，你一定很累。",
        "先讓自己喘口氣，我在這裡等你。",
        "不用急，你現在的感受是真實的。"],
    3: ["我還在聽，繼續說說看。",
        "謝謝你願意說出來。",
        "你說的這些我都聽到了。"],
    2: ["嗯，我在這裡陪著你。",
        "我們可以慢慢來，不急。",
        "你剛才說的，我一直在聽。"],
    1: ["這種感覺不到的狀態，本身也是一種訊號。",
        "不需要說什麼，我就在這裡。",
        "我們可以就這樣靜一靜。"],
    0: ["我在這裡，你可以繼續說。",
        "謝謝你今天願意開口。",
        "我聽到你了。"],
}

HIGH_VOLATILITY_FALLBACK = ["我聽到了。", "你說的我都接住了。", "嗯。繼續說。"]
STAGNANT_FALLBACK = ["沒關係，不用說。", "我在這裡。", "我們可以安靜一會兒。"]


# ── 轉介語句 ─────────────────────────────────────────────

REFERRAL_MESSAGES = {
    5: (
        "作為一個 AI，這裡的文字無法單獨承接這麼巨大的痛苦。\n"
        "請撥打安心專線 1925，讓真人的專業陪著你。24小時都有人接。"
    ),
    4: (
        "你現在承受著很多，這已經超出文字對話能給予的承接。\n"
        "安心專線 1925 是 24 小時的，隨時可以撥。"
    ),
    1: (
        "這種感覺不到痛苦的麻木，其實是身體為了保護你啟動的機制。\n"
        "在實體心理諮商中，心理師常常會陪著人溫柔地解開這個麻木。"
    ),
}

REFERRAL_DAMPENER_POOL = [
    "如果之後有機會，帶著這個部分去和諮商師談談會很有幫助。",
    "實體的心理諮商可以讓你在更安全、更完整的空間繼續這樣的探索。",
    "有時候文字能觸及的深度是有限的，諮商師可以陪你走到更深的地方。",
]


# ── Circuit Breaker ──────────────────────────────────────

class EnhancedCircuitBreaker:
    """
    三態 Circuit Breaker
    failure_threshold=3：連續 3 次失敗 → OPEN
    reset_timeout=60：60 秒後進入 HALF_OPEN
    half_open_max_calls=2：2 次成功才回 CLOSED
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        reset_timeout: int = 60,
        half_open_max_calls: int = 2,
    ):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.half_open_max_calls = half_open_max_calls

        self.state = "CLOSED"
        self.failure_count = 0
        self.half_open_calls = 0
        self.opened_at: float = 0

    def record_success(self):
        self.failure_count = 0
        if self.state == "HALF_OPEN":
            self.half_open_calls += 1
            if self.half_open_calls >= self.half_open_max_calls:
                self.state = "CLOSED"
                self.half_open_calls = 0
                print("[CB] CLOSED")

    def record_failure(self):
        self.failure_count += 1
        if self.state == "HALF_OPEN":
            self.state = "OPEN"
            self.opened_at = time.time()
            print("[CB] HALF_OPEN → OPEN")
        elif self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            self.opened_at = time.time()
            print(f"[CB] OPEN（連續失敗 {self.failure_count} 次）")

    def should_use_fallback(self) -> bool:
        if self.state == "CLOSED":
            return False
        if self.state == "OPEN":
            if time.time() - self.opened_at >= self.reset_timeout:
                self.state = "HALF_OPEN"
                self.half_open_calls = 0
                print("[CB] OPEN → HALF_OPEN")
                return False
            return True
        return False  # HALF_OPEN 允許嘗試

    def can_attempt(self) -> bool:
        return not self.should_use_fallback()

    def get_fallback(self, session_or_arousal) -> str:
        if isinstance(session_or_arousal, int):
            pool = FALLBACK_POOL.get(session_or_arousal, FALLBACK_POOL[0])
            return random.choice(pool)
        session = session_or_arousal
        state_label = session.get("fast_path_state", "NORMAL")
        if state_label == "HIGH_VOLATILITY":
            return random.choice(HIGH_VOLATILITY_FALLBACK)
        if state_label == "STAGNANT":
            return random.choice(STAGNANT_FALLBACK)
        arousal = session.get("psych", {}).get("arousal_level", 0)
        pool = FALLBACK_POOL.get(arousal, FALLBACK_POOL[0])
        return random.choice(pool)


# 全域單例
_breaker = EnhancedCircuitBreaker()


def get_breaker() -> EnhancedCircuitBreaker:
    return _breaker


async def safe_claude_call(
    prompt: str,
    session: dict,
    max_tokens: int = 400,
    timeout: float = 20.0,
    model: str = "claude-sonnet-4-6",
) -> tuple[str, bool]:
    """
    帶 Circuit Breaker 保護的 Claude API 呼叫
    Returns: (reply, used_fallback)
    """
    breaker = get_breaker()

    if breaker.should_use_fallback():
        return breaker.get_fallback(session), True

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            res = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            data = res.json()
            if data.get("type") == "error":
                raise ValueError(data["error"]["message"])
            reply = data["content"][0]["text"].strip()
            breaker.record_success()
            return reply, False

    except Exception as e:
        print(f"[CB] API 失敗：{e}")
        breaker.record_failure()
        return breaker.get_fallback(session), True


# ── 漸進式轉介阻尼器 ─────────────────────────────────────

async def apply_referral(
    reply: str,
    user_id: str,
    arousal_level: int,
    session: dict,
) -> str:
    """
    依 Arousal Level 決定是否附上轉介訊息
    次數限制從 DB 讀取（持久，重啟不歸零）
    """
    try:
        from services.db_persistent import count_today_referrals, log_referral
    except ImportError:
        return reply  # DB 不可用時不轉介

    # Arousal 5：強制
    if arousal_level == 5:
        await log_referral(user_id, "crisis")
        return reply + "\n\n" + REFERRAL_MESSAGES[5]

    # Arousal 4：強烈建議
    if arousal_level == 4:
        await log_referral(user_id, "strong")
        return reply + "\n\n" + REFERRAL_MESSAGES[4]

    # Arousal 1：麻木說明
    if arousal_level == 1:
        count = await count_today_referrals(user_id, "routine")
        if count < 3:
            await log_referral(user_id, "routine")
            return reply + "\n\n" + REFERRAL_MESSAGES[1]
        return reply

    # Arousal 2-3：每日最多 3 次日常推廣
    count = await count_today_referrals(user_id, "routine")
    if count < 3 and random.random() < 0.3:
        await log_referral(user_id, "routine")
        return reply + "\n\n" + random.choice(REFERRAL_DAMPENER_POOL)

    return reply
