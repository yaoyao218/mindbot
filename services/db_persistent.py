"""
P2 資料庫持久化（MariaDB / MySQL）
使用 aiomysql 非同步連線
"""

import os
import json
import time
import aiomysql
from typing import Optional

_pool: Optional[aiomysql.Pool] = None


async def get_pool() -> aiomysql.Pool:
    global _pool
    if _pool is None:
        _pool = await aiomysql.create_pool(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", 3306)),
            user=os.environ.get("DB_USER", "mindbot"),
            password=os.environ.get("DB_PASSWORD", ""),
            db=os.environ.get("DB_NAME", "mindbot"),
            charset="utf8mb4",
            autocommit=True,
            minsize=2,
            maxsize=10
        )
    return _pool


async def init_db():
    """建立所有資料表（幂等）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # sessions 表
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    user_id VARCHAR(64) PRIMARY KEY,
                    data JSON NOT NULL,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            # session_messages 表
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS session_messages (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    role ENUM('user','bot') NOT NULL,
                    text TEXT NOT NULL,
                    created_at BIGINT NOT NULL,
                    INDEX idx_user_id (user_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            # session_psych 表（心理診斷狀態，每輪紀錄）
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS session_psych (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    arousal_level TINYINT NOT NULL,
                    defense_mechanism VARCHAR(32),
                    alliance_rupture VARCHAR(32),
                    emotion VARCHAR(32),
                    cognition VARCHAR(32),
                    method VARCHAR(32),
                    created_at BIGINT NOT NULL,
                    INDEX idx_user_id (user_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            # checkins 表
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS checkins (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    emotion VARCHAR(32) NOT NULL,
                    cognition VARCHAR(32),
                    need VARCHAR(32),
                    user_text TEXT,
                    timestamp BIGINT NOT NULL,
                    INDEX idx_user_id (user_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

            # referral_log 表（轉介提示次數）
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS referral_log (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    referral_type ENUM('crisis','strong','routine') NOT NULL,
                    created_at BIGINT NOT NULL,
                    INDEX idx_user_date (user_id, created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

    print("[DB] Tables initialized")


# ─── Session CRUD ───────────────────────────────────────────

async def get_session(user_id: str) -> dict:
    pool = await get_pool()
    now = int(time.time())
    TTL = 7200  # 2 小時

    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT data, updated_at FROM sessions WHERE user_id = %s",
                (user_id,)
            )
            row = await cur.fetchone()

            if row and (now - row["updated_at"]) < TTL:
                return json.loads(row["data"])

    # 建立新 session
    new_session = {
        "user_id": user_id,
        "in_dialog": False,
        "method": None,
        "step": 0,
        "phase": 0,
        "turn": 0,
        "core_belief": None,
        "labels": {},
        "psych": {},
        "history": [],
        "pending_checkin": None,
        "_created_at": now,
        "_updated_at": now
    }
    await save_session(user_id, new_session)
    return new_session


async def save_session(user_id: str, session: dict):
    session["_updated_at"] = int(time.time())
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO sessions (user_id, data, created_at, updated_at)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE data = VALUES(data), updated_at = VALUES(updated_at)
            """, (
                user_id,
                json.dumps(session, ensure_ascii=False),
                session.get("_created_at", int(time.time())),
                session["_updated_at"]
            ))


async def clear_session(user_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))


# ─── Messages ───────────────────────────────────────────────

async def save_message(user_id: str, role: str, text: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO session_messages (user_id, role, text, created_at) VALUES (%s, %s, %s, %s)",
                (user_id, role, text, int(time.time()))
            )


# ─── Psych state ────────────────────────────────────────────

async def save_psych_state(user_id: str, psych: dict):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO session_psych
                (user_id, arousal_level, defense_mechanism, alliance_rupture,
                 emotion, cognition, method, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                user_id,
                psych.get("arousal_level", 3),
                psych.get("defense_mechanism", "NONE"),
                psych.get("alliance_rupture", "NONE"),
                psych.get("emotion"),
                psych.get("cognition"),
                psych.get("method"),
                int(time.time())
            ))


# ─── Checkins ───────────────────────────────────────────────

async def save_checkin(user_id: str, data: dict):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO checkins (user_id, emotion, cognition, need, user_text, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                user_id,
                data.get("emotion"),
                data.get("cognition"),
                data.get("need"),
                data.get("user_text"),
                data.get("timestamp", int(time.time()))
            ))


# ─── Referral damper ────────────────────────────────────────

async def count_today_referrals(user_id: str, referral_type: str = "routine") -> int:
    """今日特定類型轉介次數"""
    pool = await get_pool()
    today_start = int(time.time()) - (int(time.time()) % 86400)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT COUNT(*) as cnt FROM referral_log
                WHERE user_id = %s AND referral_type = %s AND created_at >= %s
            """, (user_id, referral_type, today_start))
            row = await cur.fetchone()
            return row[0] if row else 0


async def log_referral(user_id: str, referral_type: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO referral_log (user_id, referral_type, created_at) VALUES (%s, %s, %s)",
                (user_id, referral_type, int(time.time()))
            )
