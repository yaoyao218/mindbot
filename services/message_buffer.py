"""
In-process 訊息緩衝區（Redis 不可用時的 fallback）
存在記憶體中，服務重啟後清空。
每位用戶最多保留 300 則。
"""

import time
from collections import defaultdict
from typing import Optional

_buffer: dict[str, list[dict]] = defaultdict(list)
MAX_PER_USER = 300


def add(user_id: str, role: str, content: str) -> None:
    buf = _buffer[user_id]
    buf.append({
        "role":       role,
        "content":    content,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    # 只保留最後 MAX_PER_USER 則
    if len(buf) > MAX_PER_USER:
        _buffer[user_id] = buf[-MAX_PER_USER:]


def get(user_id: str) -> list[dict]:
    """取得訊息（不清除，讓用戶每次登入都能看到）"""
    return list(_buffer.get(user_id, []))


def clear(user_id: str) -> None:
    _buffer.pop(user_id, None)


def user_count() -> int:
    return len(_buffer)
