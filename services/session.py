"""
Session 管理
MVP 階段使用記憶體儲存
正式上線後替換為 Redis
"""

from typing import Optional
import time

# 記憶體 session 儲存（MVP 用）
_sessions: dict = {}
SESSION_TTL = 60 * 60 * 2  # 2小時


async def get_session(user_id: str) -> dict:
    """取得用戶 session，不存在則建立新的"""
    now = time.time()
    session = _sessions.get(user_id)

    # session 不存在或已過期
    if not session or now - session.get("_updated_at", 0) > SESSION_TTL:
        session = {
            "user_id": user_id,
            "in_dialog": False,
            "method": None,
            "step": 0,
            "core_belief": None,
            "labels": {},
            "history": [],
            "pending_checkin": None,
            "_created_at": now,
            "_updated_at": now
        }
        _sessions[user_id] = session

    return session


async def save_session(user_id: str, session: dict):
    """儲存 session"""
    session["_updated_at"] = time.time()
    _sessions[user_id] = session


async def clear_session(user_id: str):
    """清除 session（對話結束時使用）"""
    if user_id in _sessions:
        del _sessions[user_id]
