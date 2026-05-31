"""
P2 資料庫持久化（MariaDB / MySQL）
使用 aiomysql 非同步連線

Tables:
  sessions         - 對話狀態（每用戶一筆）
  session_messages - 每輪訊息紀錄
  session_psych    - 每輪心理診斷狀態（情緒曲線）
  checkins         - 每日簽到
  referral_log     - 轉介提示次數（持久阻尼器）
  archives         - 月度歸檔摘要
"""

import os
import json
import time
from datetime import datetime, date
from typing import Optional

import aiomysql

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
            maxsize=10,
        )
    return _pool


# ── DDL ──────────────────────────────────────────────────

_CREATE_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS sessions (
        user_id         VARCHAR(64)  PRIMARY KEY,
        data            JSON         NOT NULL,
        turn            INT          NOT NULL DEFAULT 0,
        current_method  VARCHAR(32),
        last_arousal    TINYINT      DEFAULT 2,
        created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS session_messages (
        id          BIGINT      AUTO_INCREMENT PRIMARY KEY,
        user_id     VARCHAR(64) NOT NULL,
        role        ENUM('user','bot') NOT NULL,
        content     TEXT        NOT NULL,
        created_at  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_user_created (user_id, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS session_psych (
        id              BIGINT      AUTO_INCREMENT PRIMARY KEY,
        user_id         VARCHAR(64) NOT NULL,
        turn            INT         NOT NULL,
        arousal         TINYINT,
        emotion         VARCHAR(32),
        cognition       VARCHAR(32),
        defense         VARCHAR(32),
        rupture         VARCHAR(32),
        method          VARCHAR(32),
        created_at      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_user_turn (user_id, turn)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS checkins (
        id           BIGINT      AUTO_INCREMENT PRIMARY KEY,
        user_id      VARCHAR(64) NOT NULL,
        checked_date DATE        NOT NULL,
        emotion      VARCHAR(32),
        cognition    VARCHAR(32),
        need         VARCHAR(32),
        note         TEXT,
        UNIQUE KEY uq_user_date (user_id, checked_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS referral_log (
        id              BIGINT      AUTO_INCREMENT PRIMARY KEY,
        user_id         VARCHAR(64) NOT NULL,
        referral_type   ENUM('crisis','strong','routine') NOT NULL,
        created_at      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_user_date (user_id, created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS archives (
        id          BIGINT      AUTO_INCREMENT PRIMARY KEY,
        user_id     VARCHAR(64) NOT NULL,
        year_month  CHAR(7)     NOT NULL,
        summary     TEXT,
        stats       JSON,
        raw_count   INT         DEFAULT 0,
        created_at  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_user_ym (user_id, year_month)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


async def init_db() -> None:
    """建立所有資料表（幂等）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            for ddl in _CREATE_TABLES:
                await cur.execute(ddl)
    print("[DB] Tables initialized")


# ── Sessions ─────────────────────────────────────────────

SESSION_TTL = 7200  # 2 小時


async def get_session(user_id: str) -> dict:
    pool = await get_pool()
    now = datetime.utcnow()

    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT data, updated_at FROM sessions WHERE user_id = %s",
                (user_id,)
            )
            row = await cur.fetchone()

            if row:
                age = (now - row["updated_at"]).total_seconds()
                if age < SESSION_TTL:
                    return json.loads(row["data"])

    # 新 session
    new_session = {
        "user_id": user_id,
        "in_dialog": False,
        "method": None,
        "phase": 0,
        "step": 0,
        "total_turn": 0,
        "core_belief": None,
        "labels": {},
        "psych": {},
        "history": [],
        "pending_checkin": None,
        "fast_path_state": "NORMAL",
    }
    await save_session(user_id, new_session)
    return new_session


async def save_session(user_id: str, session: dict) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO sessions (user_id, data, turn, current_method, last_arousal)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    data           = VALUES(data),
                    turn           = VALUES(turn),
                    current_method = VALUES(current_method),
                    last_arousal   = VALUES(last_arousal),
                    updated_at     = CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    json.dumps(session, ensure_ascii=False),
                    session.get("total_turn", 0),
                    session.get("method"),
                    session.get("psych", {}).get("arousal_level", 2),
                )
            )


async def clear_session(user_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM sessions WHERE user_id = %s", (user_id,)
            )


# ── Messages ─────────────────────────────────────────────

async def append_message(user_id: str, role: str, text: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO session_messages (user_id, role, content) VALUES (%s, %s, %s)",
                (user_id, role, text)
            )


async def get_messages_by_month(
    user_id: str, year: int, month: int
) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                """
                SELECT role, content, created_at
                FROM session_messages
                WHERE user_id = %s
                  AND YEAR(created_at) = %s
                  AND MONTH(created_at) = %s
                ORDER BY created_at
                """,
                (user_id, year, month)
            )
            return await cur.fetchall()


async def delete_messages_by_month(
    user_id: str, year: int, month: int
) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM session_messages
                WHERE user_id = %s
                  AND YEAR(created_at) = %s
                  AND MONTH(created_at) = %s
                """,
                (user_id, year, month)
            )
            return cur.rowcount


# ── Psych state ──────────────────────────────────────────

async def save_psych_state(user_id: str, psych: dict, turn: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO session_psych
                (user_id, turn, arousal, emotion, cognition, defense, rupture, method)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id, turn,
                    psych.get("arousal_level"),
                    psych.get("emotion"),
                    psych.get("cognition"),
                    psych.get("defense_mechanism"),
                    psych.get("alliance_rupture"),
                    psych.get("method"),
                )
            )


# ── Checkins ─────────────────────────────────────────────

async def save_checkin(user_id: str, data: dict) -> None:
    pool = await get_pool()
    checked_date = date.today()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO checkins (user_id, checked_date, emotion, cognition, need, note)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    emotion   = VALUES(emotion),
                    cognition = VALUES(cognition),
                    need      = VALUES(need),
                    note      = VALUES(note)
                """,
                (
                    user_id, checked_date,
                    data.get("emotion"),
                    data.get("cognition"),
                    data.get("need"),
                    data.get("user_text"),
                )
            )


# ── Referral log ─────────────────────────────────────────

async def count_today_referrals(
    user_id: str, referral_type: str = "routine"
) -> int:
    pool = await get_pool()
    today = date.today()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT COUNT(*) FROM referral_log
                WHERE user_id = %s
                  AND referral_type = %s
                  AND DATE(created_at) = %s
                """,
                (user_id, referral_type, today)
            )
            row = await cur.fetchone()
            return row[0] if row else 0


async def log_referral(user_id: str, referral_type: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO referral_log (user_id, referral_type) VALUES (%s, %s)",
                (user_id, referral_type)
            )


# ── Archives ─────────────────────────────────────────────

async def get_users_with_old_data(year: int, month: int) -> list[str]:
    """取得在指定年月有訊息紀錄的所有 user_id"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT DISTINCT user_id FROM session_messages
                WHERE YEAR(created_at) = %s AND MONTH(created_at) = %s
                """,
                (year, month)
            )
            rows = await cur.fetchall()
            return [r[0] for r in rows]


async def save_archive(
    user_id: str,
    year_month: str,
    summary: str,
    stats: dict,
    raw_count: int,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO archives (user_id, year_month, summary, stats, raw_count)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    summary   = VALUES(summary),
                    stats     = VALUES(stats),
                    raw_count = VALUES(raw_count)
                """,
                (
                    user_id, year_month, summary,
                    json.dumps(stats, ensure_ascii=False),
                    raw_count,
                )
            )
