"""
資料庫持久化層 — PostgreSQL (asyncpg)
環境變數：DATABASE_URL (Railway 提供)

Tables:
  sessions         - 對話狀態（每用戶一筆）
  session_messages - 每輪訊息紀錄
  session_psych    - 每輪心理診斷狀態
  checkins         - 每日簽到
  referral_log     - 轉介提示次數
  archives         - 月度歸檔摘要
  emotion_dictionary - 情緒詞典解鎖
  daily_questions  - 今日一問紀錄
  push_schedule    - 推播時間設定
  emotion_calendar - 情緒月曆
  milestone_log    - 里程碑觸發記錄
"""

import os
import json
import time
from datetime import datetime, date
from typing import Optional

import asyncpg

_pool: Optional[asyncpg.Pool] = None
_pool_failed: bool = False


async def get_pool() -> asyncpg.Pool:
    global _pool, _pool_failed
    if _pool_failed:
        raise RuntimeError("DB unavailable, using memory mode")
    if _pool is None:
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            _pool_failed = True
            raise RuntimeError("DATABASE_URL not set")
        try:
            # Railway DATABASE_URL 有時以 postgres:// 開頭，需換成 postgresql://
            if url.startswith("postgres://"):
                url = "postgresql://" + url[len("postgres://"):]
            _pool = await asyncpg.create_pool(
                url,
                min_size=2,
                max_size=10,
                command_timeout=30,
            )
        except Exception as e:
            _pool_failed = True
            print(f"[DB] Connection failed, switching to memory mode: {e}")
            raise RuntimeError(f"DB unavailable: {e}")
    return _pool


# ── DDL ──────────────────────────────────────────────────

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS sessions (
    user_id         VARCHAR(64)  PRIMARY KEY,
    data            JSONB        NOT NULL DEFAULT '{}',
    turn            INT          NOT NULL DEFAULT 0,
    current_method  VARCHAR(32),
    last_arousal    SMALLINT     DEFAULT 2,
    streak_count    INT          DEFAULT 0,
    streak_last_day DATE         DEFAULT NULL,
    tree_stage      SMALLINT     DEFAULT 0,
    tree_water      SMALLINT     DEFAULT 0,
    tree_sun        SMALLINT     DEFAULT 0,
    tree_nutrient   SMALLINT     DEFAULT 0,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS session_messages (
    id          BIGSERIAL    PRIMARY KEY,
    user_id     VARCHAR(64)  NOT NULL,
    role        VARCHAR(4)   NOT NULL CHECK (role IN ('user','bot')),
    content     TEXT         NOT NULL,
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sm_user_created ON session_messages (user_id, created_at);

CREATE TABLE IF NOT EXISTS session_psych (
    id          BIGSERIAL    PRIMARY KEY,
    user_id     VARCHAR(64)  NOT NULL,
    turn        INT          NOT NULL,
    arousal     SMALLINT,
    emotion     VARCHAR(32),
    cognition   VARCHAR(32),
    defense     VARCHAR(32),
    rupture     VARCHAR(32),
    method      VARCHAR(32),
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sp_user_turn ON session_psych (user_id, turn);

CREATE TABLE IF NOT EXISTS checkins (
    id           BIGSERIAL    PRIMARY KEY,
    user_id      VARCHAR(64)  NOT NULL,
    checked_date DATE         NOT NULL,
    emotion      VARCHAR(32),
    cognition    VARCHAR(32),
    need         VARCHAR(32),
    note         TEXT,
    UNIQUE (user_id, checked_date)
);

CREATE TABLE IF NOT EXISTS referral_log (
    id              BIGSERIAL    PRIMARY KEY,
    user_id         VARCHAR(64)  NOT NULL,
    referral_type   VARCHAR(16)  NOT NULL CHECK (referral_type IN ('crisis','strong','routine')),
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rl_user_date ON referral_log (user_id, created_at);

CREATE TABLE IF NOT EXISTS archives (
    id          BIGSERIAL    PRIMARY KEY,
    user_id     VARCHAR(64)  NOT NULL,
    year_month  CHAR(7)      NOT NULL,
    summary     TEXT,
    stats       JSONB,
    raw_count   INT          DEFAULT 0,
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, year_month)
);

CREATE TABLE IF NOT EXISTS emotion_dictionary (
    id          SERIAL       PRIMARY KEY,
    user_id     VARCHAR(64)  NOT NULL,
    word_id     VARCHAR(32)  NOT NULL,
    unlocked_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, word_id)
);

CREATE TABLE IF NOT EXISTS daily_questions (
    id              BIGSERIAL    PRIMARY KEY,
    user_id         VARCHAR(64)  NOT NULL,
    question_text   TEXT         NOT NULL,
    sent_date       DATE         NOT NULL,
    UNIQUE (user_id, sent_date)
);

CREATE TABLE IF NOT EXISTS push_schedule (
    user_id     VARCHAR(64)  PRIMARY KEY,
    push_hour   SMALLINT     NOT NULL DEFAULT 21,
    push_minute SMALLINT     NOT NULL DEFAULT 0,
    enabled     SMALLINT     NOT NULL DEFAULT 1,
    updated_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS emotion_calendar (
    id              BIGSERIAL    PRIMARY KEY,
    user_id         VARCHAR(64)  NOT NULL,
    record_date     DATE         NOT NULL,
    emotion_emoji   VARCHAR(8),
    emotion_label   VARCHAR(32),
    UNIQUE (user_id, record_date)
);

CREATE TABLE IF NOT EXISTS milestone_log (
    id              BIGSERIAL    PRIMARY KEY,
    user_id         VARCHAR(64)  NOT NULL,
    milestone_days  SMALLINT     NOT NULL,
    observation     TEXT         DEFAULT '',
    triggered_at    TIMESTAMP    NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, milestone_days)
);
"""


async def init_db() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(_CREATE_TABLES)
    print("[DB] PostgreSQL tables initialized")


# ── Sessions ─────────────────────────────────────────────

SESSION_TTL = 7200  # 2 小時


async def get_session(user_id: str) -> dict:
    pool = await get_pool()
    now = datetime.utcnow()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT data, updated_at FROM sessions WHERE user_id = $1",
            user_id
        )
        if row:
            age = (now - row["updated_at"].replace(tzinfo=None)).total_seconds()
            if age < SESSION_TTL:
                return dict(row["data"]) if isinstance(row["data"], dict) else json.loads(row["data"])

    new_session = {
        "user_id": user_id, "in_dialog": False,
        "method": None, "phase": 0, "step": 0,
        "total_turn": 0, "core_belief": None,
        "labels": {}, "psych": {}, "history": [],
        "pending_checkin": None, "fast_path_state": "NORMAL",
    }
    await save_session(user_id, new_session)
    return new_session


async def save_session(user_id: str, session: dict) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (user_id, data, turn, current_method, last_arousal)
            VALUES ($1, $2::jsonb, $3, $4, $5)
            ON CONFLICT (user_id) DO UPDATE SET
                data           = EXCLUDED.data,
                turn           = EXCLUDED.turn,
                current_method = EXCLUDED.current_method,
                last_arousal   = EXCLUDED.last_arousal,
                updated_at     = NOW()
            """,
            user_id,
            json.dumps(session, ensure_ascii=False),
            session.get("total_turn", 0),
            session.get("method"),
            session.get("psych", {}).get("arousal_level", 2),
        )


async def clear_session(user_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM sessions WHERE user_id = $1", user_id)


# ── Messages ─────────────────────────────────────────────

async def append_message(user_id: str, role: str, text: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO session_messages (user_id, role, content) VALUES ($1, $2, $3)",
            user_id, role, text
        )


async def get_messages_by_month(user_id: str, year: int, month: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, content, created_at
            FROM session_messages
            WHERE user_id = $1
              AND EXTRACT(YEAR FROM created_at) = $2
              AND EXTRACT(MONTH FROM created_at) = $3
            ORDER BY created_at
            """,
            user_id, year, month
        )
        return [{"role": r["role"], "content": r["content"],
                 "created_at": r["created_at"].isoformat()} for r in rows]


async def delete_messages_by_month(user_id: str, year: int, month: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM session_messages
            WHERE user_id = $1
              AND EXTRACT(YEAR FROM created_at) = $2
              AND EXTRACT(MONTH FROM created_at) = $3
            """,
            user_id, year, month
        )
        return int(result.split()[-1])


# ── Psych state ──────────────────────────────────────────

async def save_psych_state(user_id: str, psych: dict, turn: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO session_psych
            (user_id, turn, arousal, emotion, cognition, defense, rupture, method)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            """,
            user_id, turn,
            psych.get("arousal_level"),
            psych.get("emotion"),
            psych.get("cognition"),
            psych.get("defense_mechanism"),
            psych.get("alliance_rupture"),
            psych.get("method"),
        )


# ── Checkins ─────────────────────────────────────────────

async def save_checkin(user_id: str, data: dict) -> None:
    pool = await get_pool()
    checked_date = date.today()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO checkins (user_id, checked_date, emotion, cognition, need, note)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (user_id, checked_date) DO UPDATE SET
                emotion   = EXCLUDED.emotion,
                cognition = EXCLUDED.cognition,
                need      = EXCLUDED.need,
                note      = EXCLUDED.note
            """,
            user_id, checked_date,
            data.get("emotion"),
            data.get("cognition"),
            data.get("need"),
            data.get("user_text"),
        )


# ── Referral log ─────────────────────────────────────────

async def count_today_referrals(user_id: str, referral_type: str = "routine") -> int:
    pool = await get_pool()
    today = date.today()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """
            SELECT COUNT(*) FROM referral_log
            WHERE user_id = $1 AND referral_type = $2
              AND created_at::date = $3
            """,
            user_id, referral_type, today
        )
        return val or 0


async def log_referral(user_id: str, referral_type: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO referral_log (user_id, referral_type) VALUES ($1, $2)",
            user_id, referral_type
        )


# ── Archives ─────────────────────────────────────────────

async def get_users_with_old_data(year: int, month: int) -> list[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT user_id FROM session_messages
            WHERE EXTRACT(YEAR FROM created_at)=$1
              AND EXTRACT(MONTH FROM created_at)=$2
            """,
            year, month
        )
        return [r["user_id"] for r in rows]


async def save_archive(user_id: str, year_month: str, summary: str,
                       stats: dict, raw_count: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO archives (user_id, year_month, summary, stats, raw_count)
            VALUES ($1, $2, $3, $4::jsonb, $5)
            ON CONFLICT (user_id, year_month) DO UPDATE SET
                summary   = EXCLUDED.summary,
                stats     = EXCLUDED.stats,
                raw_count = EXCLUDED.raw_count
            """,
            user_id, year_month, summary,
            json.dumps(stats, ensure_ascii=False), raw_count
        )


# ── Emotion Dictionary ───────────────────────────────────

async def get_unlocked_words(user_id: str) -> set[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT word_id FROM emotion_dictionary WHERE user_id = $1", user_id
        )
        return {r["word_id"] for r in rows}


async def unlock_emotion_word(user_id: str, word_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO emotion_dictionary (user_id, word_id)
            VALUES ($1, $2) ON CONFLICT DO NOTHING
            """,
            user_id, word_id
        )


# ── Emotion Calendar ──────────────────────────────────────

async def save_emotion_calendar(user_id: str, record_date: date,
                                 emoji: str, label: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO emotion_calendar (user_id, record_date, emotion_emoji, emotion_label)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, record_date) DO UPDATE SET
                emotion_emoji = EXCLUDED.emotion_emoji,
                emotion_label = EXCLUDED.emotion_label
            """,
            user_id, record_date, emoji, label
        )


async def get_emotion_calendar(user_id: str, year: int, month: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT record_date, emotion_emoji, emotion_label
            FROM emotion_calendar
            WHERE user_id=$1
              AND EXTRACT(YEAR FROM record_date)=$2
              AND EXTRACT(MONTH FROM record_date)=$3
            ORDER BY record_date
            """,
            user_id, year, month
        )
        return [{"record_date": r["record_date"].isoformat(),
                 "emotion_emoji": r["emotion_emoji"],
                 "emotion_label": r["emotion_label"]} for r in rows]


async def get_streak_days(user_id: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT record_date FROM emotion_calendar
            WHERE user_id = $1 ORDER BY record_date DESC LIMIT 100
            """,
            user_id
        )
    if not rows:
        return 0
    from datetime import timedelta
    today = date.today()
    streak = 0
    for i, row in enumerate(rows):
        expected = today - timedelta(days=i)
        actual = row["record_date"]
        if isinstance(actual, str):
            actual = date.fromisoformat(actual)
        if actual == expected:
            streak += 1
        else:
            break
    return streak


# ── Milestone Log ─────────────────────────────────────────

async def check_and_mark_milestone(
    user_id: str, days: int, observation: str = ""
) -> bool:
    """首次觸發回傳 True，已觸發過回傳 False"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            INSERT INTO milestone_log (user_id, milestone_days, observation)
            VALUES ($1, $2, $3) ON CONFLICT DO NOTHING
            """,
            user_id, days, observation
        )
        return result == "INSERT 0 1"


async def get_user_milestones(user_id: str) -> list[dict]:
    """取得用戶所有已觸發的里程碑（含觀察文字）"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT milestone_days, observation, triggered_at
            FROM milestone_log WHERE user_id = $1
            ORDER BY milestone_days
            """,
            user_id
        )
        return [
            {
                "days":        r["milestone_days"],
                "observation": r["observation"] or "",
                "triggered_at": r["triggered_at"].isoformat() if r["triggered_at"] else "",
            }
            for r in rows
        ]


# ── Conversation Days Count ───────────────────────────────

async def count_conversation_days(user_id: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            """
            SELECT COUNT(DISTINCT created_at::date)
            FROM session_messages
            WHERE user_id = $1 AND role = 'user'
            """,
            user_id
        )
        return val or 0


# ── Top Keywords ─────────────────────────────────────────

async def get_top_keywords(user_id: str, limit: int = 5) -> list[str]:
    import re
    from collections import Counter

    STOPWORDS = {
        "的", "了", "是", "我", "你", "他", "她", "它", "都", "也", "很", "在",
        "有", "就", "不", "這", "那", "但", "和", "或", "把", "被", "會", "想",
        "說", "到", "從", "以", "為", "與", "而", "其", "如", "所", "已", "好",
        "嗯", "啊", "哦", "喔", "吧", "呢", "嗎", "呀", "什麼", "怎麼", "為什麼",
        "因為", "所以", "然後", "但是", "不過", "還是", "還有", "一個", "一種",
        "感覺", "覺得", "知道", "沒有", "可以", "可能", "應該", "需要", "自己",
    }

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT content FROM session_messages
            WHERE user_id=$1 AND role='user'
            ORDER BY created_at DESC LIMIT 200
            """,
            user_id
        )

    texts = " ".join(r["content"] for r in rows)
    words = re.findall(r"[一-鿿]{2,4}", texts)
    counter = Counter(w for w in words if w not in STOPWORDS)
    return [w for w, _ in counter.most_common(limit)]


# ── Streak (sessions 欄位同步) ────────────────────────────

async def update_streak_db(user_id: str, streak_count: int,
                            streak_last_day: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET streak_count=$1, streak_last_day=$2 WHERE user_id=$3",
            streak_count, streak_last_day, user_id
        )


# ── Arousal History ───────────────────────────────────────

async def get_arousal_history_7d(user_id: str) -> list[int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT arousal FROM session_psych
            WHERE user_id=$1
              AND created_at >= NOW() - INTERVAL '7 days'
              AND arousal IS NOT NULL
            ORDER BY created_at
            """,
            user_id
        )
        return [r["arousal"] for r in rows]


# ── Weekly Scheduler helpers ──────────────────────────────

async def get_users_in_range(start: date, end: date) -> list[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT user_id FROM session_messages "
            "WHERE created_at::date BETWEEN $1 AND $2",
            start, end
        )
        return [r["user_id"] for r in rows]


async def get_messages_in_range(user_id: str, start: date, end: date) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content, created_at FROM session_messages "
            "WHERE user_id=$1 AND created_at::date BETWEEN $2 AND $3 "
            "ORDER BY created_at",
            user_id, start, end
        )
        return [{"role": r["role"], "content": r["content"],
                 "created_at": r["created_at"].isoformat()} for r in rows]


async def get_psych_in_range(user_id: str, start: date, end: date) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT arousal, emotion, cognition, created_at "
            "FROM session_psych "
            "WHERE user_id=$1 AND created_at::date BETWEEN $2 AND $3 "
            "ORDER BY created_at",
            user_id, start, end
        )
        return [{"arousal": r["arousal"], "emotion": r["emotion"],
                 "cognition": r["cognition"],
                 "created_at": r["created_at"].isoformat()} for r in rows]


async def delete_messages_in_range(user_id: str, start: date, end: date) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM session_messages "
            "WHERE user_id=$1 AND created_at::date BETWEEN $2 AND $3",
            user_id, start, end
        )
        return int(result.split()[-1])


# ── Push Schedule ─────────────────────────────────────────

async def get_all_push_users() -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, push_hour, push_minute FROM push_schedule WHERE enabled=1"
        )
        return [{"user_id": r["user_id"], "hour": r["push_hour"],
                 "minute": r["push_minute"]} for r in rows]
