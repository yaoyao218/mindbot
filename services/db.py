"""
資料庫服務 - MVP 階段使用記憶體儲存
正式上線後替換為 PostgreSQL
"""

from typing import Optional
import time

# 記憶體儲存（MVP 用）
_checkins: list = []
_conversations: list = []


async def save_checkin(user_id: str, record: dict):
    """儲存簽到紀錄"""
    _checkins.append({
        "user_id": user_id,
        "source": "daily_checkin",
        "created_at": time.time(),
        **record
    })
    print(f"[DB] 簽到儲存：{user_id} - {record.get('emotion')}")


async def save_conversation(user_id: str, session: dict):
    """儲存對話紀錄"""
    _conversations.append({
        "user_id": user_id,
        "method": session.get("method"),
        "labels": session.get("labels"),
        "history": session.get("history"),
        "created_at": time.time()
    })
    print(f"[DB] 對話儲存：{user_id} - {session.get('method')}")


async def get_user_checkins(user_id: str) -> list:
    """取得用戶簽到紀錄"""
    return [c for c in _checkins if c["user_id"] == user_id]
