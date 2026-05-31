"""
Redis 緩衝區讀寫
- 對話暫存（24hr TTL）：用戶登入時拉取新對話紀錄
- 週報等待領取（90天 TTL）：週排程完成後等待用戶下次登入
- 同步時間戳：記錄用戶上次拉取到哪一週

需要環境變數：REDIS_URL（e.g. redis://localhost:6379）
"""

import os
import json
from typing import Optional

import redis.asyncio as redis

_pool: Optional[redis.ConnectionPool] = None

CONV_TTL    = 86400        # 24 小時
ARCHIVE_TTL = 86400 * 30   # 30 天
WEEKLY_TTL  = 86400 * 90   # 90 天
SYNC_TTL    = 86400 * 180  # 180 天


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


# ── 週報等待區 ───────────────────────────────────────────

async def put_weekly_report(user_id: str, week_id: str, report: dict) -> None:
    """週排程完成後，將週報放入等待區（key: weekly:{user_id}:{week_id}）"""
    r = _client()
    key = f"weekly:{user_id}:{week_id}"
    await r.set(key, json.dumps(report, ensure_ascii=False), ex=WEEKLY_TTL)


async def pop_weekly_report(user_id: str, week_id: str) -> Optional[dict]:
    """用戶登入時拉取並清除指定週報"""
    r = _client()
    key = f"weekly:{user_id}:{week_id}"
    raw = await r.get(key)
    if raw:
        await r.delete(key)
        return json.loads(raw)
    return None


async def list_pending_weekly(user_id: str) -> list[str]:
    """列出該用戶所有待領週報的 week_id，已排序"""
    r = _client()
    keys = await r.keys(f"weekly:{user_id}:*")
    return sorted([k.split(":")[-1] for k in keys])


# ── 同步時間戳 ───────────────────────────────────────────

async def get_last_sync(user_id: str) -> Optional[str]:
    """取得用戶上次同步的 week_id"""
    r = _client()
    return await r.get(f"last_sync:{user_id}")


async def set_last_sync(user_id: str, week_id: str) -> None:
    """更新用戶上次同步的 week_id"""
    r = _client()
    await r.set(f"last_sync:{user_id}", week_id, ex=SYNC_TTL)
