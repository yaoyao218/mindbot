"""
Bot 發送一次性登入 token
用戶傳 "登入" → Bot 回傳一個 10 分鐘有效的連結
用戶點連結 → 網站直接登入，不走 LINE OAuth

token 格式：隨機 UUID，存在 in-process dict
"""

import uuid
import time
from typing import Optional

_tokens: dict[str, dict] = {}   # token → {user_id, expires}
TOKEN_TTL = 600                  # 10 分鐘


def create_token(user_id: str) -> str:
    """產生並儲存一次性 token，回傳 token 字串"""
    # 清掉該用戶的舊 token
    for t, v in list(_tokens.items()):
        if v["user_id"] == user_id:
            del _tokens[t]

    token = uuid.uuid4().hex
    _tokens[token] = {
        "user_id": user_id,
        "expires": time.time() + TOKEN_TTL,
    }
    return token


def consume_token(token: str) -> Optional[str]:
    """驗證並使用 token（只能用一次），回傳 user_id 或 None"""
    entry = _tokens.get(token)
    if not entry:
        return None
    if time.time() > entry["expires"]:
        del _tokens[token]
        return None
    del _tokens[token]          # 一次性，用後即刪
    return entry["user_id"]


def cleanup():
    """清除過期 token"""
    now = time.time()
    for t in list(_tokens):
        if _tokens[t]["expires"] < now:
            del _tokens[t]
