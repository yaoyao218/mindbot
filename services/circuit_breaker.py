"""
P2 斷路器（Circuit Breaker）
三態狀態機：CLOSED / OPEN / HALF_OPEN
連續 3 次 API 失敗 → OPEN，靜態兜底語句池
"""

import time
from enum import Enum
from typing import Optional

class State(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


# 靜態兜底語句池（依 Arousal Level）
FALLBACK_RESPONSES = {
    1: [
        "你現在感覺怎麼樣？",
        "沒關係，我在這裡陪你。",
        "你願意說說現在的狀態嗎？"
    ],
    2: [
        "聽起來你心裡有些東西想說。",
        "謝謝你願意分享這些。",
        "你說的這些，我想多了解一點。"
    ],
    3: [
        "我聽到你了。這件事對你來說很重要。",
        "你說的讓我想多聽一些。",
        "謝謝你願意說出來。"
    ],
    4: [
        "我聽到你了。你現在承受著很多。",
        "先讓自己喘口氣。我在這裡。",
        "不需要馬上想清楚，先告訴我你現在身體有什麼感覺？"
    ],
    5: [
        "我很擔心你現在的狀態。安心專線 1925，24小時都有人接。",
        "你現在不需要一個人扛。安心專線 1925 隨時可以打。",
        "請撥打安心專線 1925，有人會陪你度過這一刻。"
    ]
}

_fallback_index: dict[int, int] = {}  # 輪替索引


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_timeout: int = 60):
        self.state = State.CLOSED
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time: Optional[float] = None

    def record_success(self):
        self.failure_count = 0
        self.state = State.CLOSED

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = State.OPEN

    def can_attempt(self) -> bool:
        if self.state == State.CLOSED:
            return True
        if self.state == State.OPEN:
            if time.time() - (self.last_failure_time or 0) > self.recovery_timeout:
                self.state = State.HALF_OPEN
                return True
            return False
        # HALF_OPEN: 允許一次嘗試
        return True

    def get_fallback(self, arousal_level: int = 3) -> str:
        level = max(1, min(5, arousal_level))
        pool = FALLBACK_RESPONSES[level]
        idx = _fallback_index.get(level, 0)
        response = pool[idx % len(pool)]
        _fallback_index[level] = idx + 1
        return response


# 全域單例
_breaker = CircuitBreaker()


def get_breaker() -> CircuitBreaker:
    return _breaker
