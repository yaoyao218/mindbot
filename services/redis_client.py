"""
Redis 快取層（Cache-First，PostgreSQL 為 Single Source of Truth）

角色分工：
  - 週報  : SETEX 快取，TTL 30 天；讀取不刪除，過期自動失效
  - 對話  : RPUSH 緩衝，TTL 24 hr；登入時讀取後清空（訊息不是 SSOT）
  - 分散式鎖: SET NX EX，TTL 30 秒，防止同一用戶連發訊息 Race Condition

需要環境變數：REDIS_URL（e.g. redis://localhost:6379）
"""

import os
import json
from typing import Optional

import redis.asyncio as redis

_pool: Optional[redis.ConnectionPool] = None

CONV_TTL    = 86400        # 24 小時
ARCHIVE_TTL = 86400 * 30   # 30 天
WEEKLY_TTL  = 86400 * 30   # 30 天（改短：PostgreSQL 是 SSOT，快取只是加速）
SYNC_TTL    = 86400 * 180  # 180 天
LOCK_TTL    = 15           # 分散式鎖 15 秒（LLM 最長生成容忍值；縮短以降低死鎖窗口）


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


# ── Archive 快取（Cache-First，PostgreSQL 為 SSOT）──────

async def put_archive(user_id: str, year_month: str, archive: dict) -> None:
    """月度排程完成後，將摘要寫入 Redis 快取（SETEX）"""
    r = _client()
    key = f"archive:{user_id}:{year_month}"
    await r.set(
        key,
        json.dumps(archive, ensure_ascii=False),
        ex=ARCHIVE_TTL,
    )


async def get_archive_cache(user_id: str, year_month: str) -> Optional[dict]:
    """讀取月度歸檔快取（不刪除）。PostgreSQL 為 SSOT，此為加速層。"""
    r = _client()
    raw = await r.get(f"archive:{user_id}:{year_month}")
    return json.loads(raw) if raw else None


async def list_cached_archives(user_id: str) -> list[str]:
    """列出 Redis 中該用戶所有有快取的月度 year_month"""
    r = _client()
    keys = await r.keys(f"archive:{user_id}:*")
    return sorted([k.split(":")[-1] for k in keys])


# ── 週報快取（Cache-First，不刪除）────────────────────────

async def put_weekly_report(user_id: str, week_id: str, report: dict) -> None:
    """
    週排程完成後，將週報寫入 Redis 快取（SETEX）。
    PostgreSQL archives 才是 SSOT；Redis 只是加速讀取。
    """
    r = _client()
    key = f"weekly:{user_id}:{week_id}"
    await r.set(key, json.dumps(report, ensure_ascii=False), ex=WEEKLY_TTL)


async def get_weekly_report_cache(user_id: str, week_id: str) -> Optional[dict]:
    """讀取 Redis 快取的週報（不刪除）。Cache miss 回傳 None。"""
    r = _client()
    raw = await r.get(f"weekly:{user_id}:{week_id}")
    return json.loads(raw) if raw else None


async def set_weekly_report_cache(
    user_id: str, week_id: str, report: dict, ttl: int = WEEKLY_TTL
) -> None:
    """將從 PostgreSQL 查到的週報回寫 Redis 快取（SETEX）。"""
    r = _client()
    await r.set(
        f"weekly:{user_id}:{week_id}",
        json.dumps(report, ensure_ascii=False),
        ex=ttl,
    )


async def list_cached_weekly(user_id: str) -> list[str]:
    """列出 Redis 中該用戶所有有快取的 week_id（已排序）。"""
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


# ── 快照臟旗標（Cache Invalidation）────────────────────
# 每次新訊息寫入後設定，迫使 /api/snapshot 跳過 6h AI 摘要快取

SNAP_DIRTY_TTL = 30 * 60    # 30 分鐘：足夠等 LIFF 重整，不會永久殘留

async def set_snapshot_dirty(user_id: str) -> None:
    """新訊息/新對話後呼叫，標記該用戶的 snapshot 快取需重新生成"""
    try:
        r = _client()
        await r.set(f"snap_dirty:{user_id}", "1", ex=SNAP_DIRTY_TTL)
    except Exception:
        pass   # Redis 不可用時靜默，不影響主流程

async def pop_snapshot_dirty(user_id: str) -> bool:
    """
    原子讀取並刪除臟旗標（GETDEL）。
    回傳 True  → 快取已過期，snapshot 應跳過 6h TTL 並重算。
    回傳 False → 快取仍有效或 Redis 不可用。
    """
    try:
        r = _client()
        result = await r.getdel(f"snap_dirty:{user_id}")
        return result is not None
    except Exception:
        return False   # 降級：視為乾淨，不強制重算

# ── 分散式鎖（防 Race Condition）────────────────────────

async def acquire_user_lock(user_id: str, ttl: int = LOCK_TTL) -> bool:
    """
    嘗試取得用戶處理鎖。
    SET NX EX：原子操作，只有第一個請求能設定成功。
    回傳 True 表示取得鎖，False 表示已有其他請求在處理中。
    """
    r = _client()
    result = await r.set(f"lock:msg:{user_id}", "1", nx=True, ex=ttl)
    return result is True


async def release_user_lock(user_id: str) -> None:
    """釋放用戶處理鎖（正常完成或異常時呼叫）"""
    r = _client()
    await r.delete(f"lock:msg:{user_id}")
