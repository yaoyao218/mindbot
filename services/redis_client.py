"""
Redis 緩衝區讀寫
- 對話暫存（24hr TTL）：用戶登入時拉取新對話紀錄
- Archive 等待領取（30天 TTL）：月度摘要等待用戶下次登入
- Circuit Breaker 狀態（可選，目前 CB 為記憶體版）

需要環境變數：REDIS_URL（e.g. redis://localhost:6379）
"""

import os
import json
from typing import Optional

import redis.asyncio as redis

_pool: Optional[redis.ConnectionPool] = None

CONV_TTL    = 86400        # 24 小時
ARCHIVE_TTL = 86400 * 30   # 30 天


def _get_pool() -> redis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(
            os.environ["REDIS_URL"],
            decode_responses=True,
            max_connections=20,
        )
    return _pool


def _client() -> redis.Redis:
    return redis.Redis(connection_pool=_get_pool())


# ── 對話緩衝區 ───────────────────────────────────────────

async def buffer_message(user_id: str, message: dict) -> None:
    """將一則對話訊息 append 進用戶緩衝 List"""
    r = _client()
    key = f"conv:{user_id}"
    await r.rpush(key, json.dumps(message, ensure_ascii=False))
    await r.expire(key, CONV_TTL)


async def pop_buffered_messages(user_id: str) -> list[dict]:
    """取出並清空用戶緩衝區（前端登入拉取時呼叫）"""
    r = _client()
    key = f"conv:{user_id}"
    raw = await r.lrange(key, 0, -1)
    if raw:
        await r.delete(key)
    return [json.loads(m) for m in raw]


# ── Archive 等待區 ───────────────────────────────────────

async def put_archive(user_id: str, year_month: str, archive: dict) -> None:
    """月度排程完成後，將摘要放入等待區"""
    r = _client()
    key = f"archive:{user_id}:{year_month}"
    await r.set(
        key,
        json.dumps(archive, ensure_ascii=False),
        ex=ARCHIVE_TTL,
    )


async def pop_archive(user_id: str, year_month: str) -> Optional[dict]:
    """用戶登入時拉取並清除 Archive"""
    r = _client()
    key = f"archive:{user_id}:{year_month}"
    raw = await r.get(key)
    if raw:
        await r.delete(key)
        return json.loads(raw)
    return None


async def list_pending_archives(user_id: str) -> list[str]:
    """列出該用戶所有待領 Archive 的 year_month"""
    r = _client()
    keys = await r.keys(f"archive:{user_id}:*")
    return [k.split(":")[-1] for k in keys]
