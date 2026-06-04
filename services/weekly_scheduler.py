"""
週報排程 — 情感考古 Pipeline
- 每週一凌晨 3 點執行（處理上週 Mon-Sun）
- AI 生成「情感考古週報」：三層地質 + 三維度氣泡 + 起承轉合敘事弧
- 組成 WeeklyReport → PostgreSQL + Redis（TTL 30天）
- 刪除原始 session_messages
"""
import json
import asyncio
import random
from datetime import datetime, date, timedelta
from typing import Optional

from services.db_persistent import (
    get_users_in_range, get_messages_in_range,
    get_psych_in_range, delete_messages_in_range, save_archive,
)
from services.redis_client import put_weekly_report
from services.llm import call_api

# ── 週 ID ────────────────────────────────────────────────
def get_week_id(d: date) -> str:
    return f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"

def get_last_week_range() -> tuple[date, date, str]:
    today    = date.today()
    last_mon = today - timedelta(days=today.weekday() + 7)
    last_sun = last_mon + timedelta(days=6)
    return last_mon, last_sun, get_week_id(last_mon)

# ── 本地統計（不走 AI）───────────────────────────────────
def compute_stats(messages: list[dict], psych_rows: list[dict]) -> dict:
    user_msgs = [m for m in messages if m["role"] == "user"]

    arousal_curve: list[dict] = [
        {"t": r["created_at"], "v": r["arousal"]}
        for r in psych_rows if r.get("arousal")
    ]

    emotion_counts: dict[str, int] = {}
    for r in psych_rows:
        e = r.get("emotion")
        if e:
            emotion_counts[e] = emotion_counts.get(e, 0) + 1

    arousals    = [r["arousal"] for r in psych_rows if r.get("arousal")]
    avg_arousal = round(sum(arousals) / len(arousals), 2) if arousals else None

    daily: dict[str, int] = {}
    for m in user_msgs:
        day = m["created_at"][:10]
        daily[day] = daily.get(day, 0) + 1

    return {
        "total_turns":    len(messages),
        "user_msg_count": len(user_msgs),
        "avg_arousal":    avg_arousal,
        "arousal_curve":  arousal_curve,
        "emotion_counts": emotion_counts,
        "daily_counts":   daily,
    }

# ── 情感考古 AI 摘要（完整 JSON Schema）────────────────────
_ARCH_SCHEMA_DESC = """
JSON Schema（嚴格照格式，不加 markdown 或前言）：
{
  "summary": "二到三句話，溫暖中性地描述本週核心情緒狀態",
  "themes": ["最多三個主題，每個不超過六字"],
  "growth_note": "一句話，本週的細微正向轉變或值得肯定之處",
  "archaeology": {
    "surface": "表層：本週最常出現的情緒反應或外顯行為，二十字以內",
    "middle": "中層：驅動這些反應的底層情緒基調，二十字以內",
    "deep": "深層：更根本的核心需求或重複的心理模式，二十字以內"
  },
  "triad": {
    "emotion":   [{"label": "情緒名稱2-4字", "value": 0-100}],
    "cognition": [{"label": "認知模式2-4字", "value": 0-100}],
    "need":      [{"label": "內在需求2-4字", "value": 0-100}]
  },
  "narrative_arc": {
    "opening":     "起：週初的情緒起點，一句話",
    "development": "承：情緒如何演變，一句話",
    "turning":     "轉：出現的轉折或頓悟（若無則寫尚未）",
    "closing":     "合：本週的情緒落點與目前內在狀態"
  },
  "end_quote": "一句有溫度的療癒結語，引用真實人物名言或詩句",
  "quote_author": "作者或來源（繁體中文）"
}

triad 補充規則：
- emotion   列出 2-4 個本週主要情緒（如疲憊、焦慮、委屈）
- cognition 列出 2-3 個主導認知模式（如自我批評、過度責任感、反芻思考）
- need      列出 2-3 個底層需求（如被理解、安全感、掌控感）
- value 代表本週該向度的強度（0=幾乎未出現，100=極為主導）
"""

async def generate_archaeology_report(
    messages: list[dict],
    psych_rows: list[dict],
    week_id: str,
) -> dict:
    """
    呼叫 LLM，依「情感考古」JSON Schema 生成完整週報。
    回傳包含所有欄位的 dict；任何欄位缺失時給安全預設值。
    """
    user_texts = [m["content"] for m in messages if m["role"] == "user"]
    sample     = "\n".join(user_texts[:45])

    # psych 摘要（輔助 LLM 判斷三維度）
    psych_summary_lines = []
    for r in psych_rows[:20]:
        parts = []
        if r.get("emotion"):   parts.append(f"情緒:{r['emotion']}")
        if r.get("cognition"): parts.append(f"認知:{r['cognition']}")
        if r.get("arousal"):   parts.append(f"喚醒:{r['arousal']}/5")
        if r.get("defense"):   parts.append(f"防衛:{r['defense']}")
        if parts:
            psych_summary_lines.append("、".join(parts))
    psych_hint = "\n".join(psych_summary_lines) or "（無診斷資料）"

    prompt = f"""以下是用戶在 {week_id} 的心事日記（用戶訊息）：
---
{sample}
---

AI 輔助心理診斷摘要：
{psych_hint}
---

你是一位溫暖、有深度的心理陪伴 AI，請對這週的用戶做「情感考古」分析。
請嚴格輸出以下 JSON，不加任何前言、後記或 markdown：

{_ARCH_SCHEMA_DESC}"""

    raw = await call_api(prompt, max_tokens=900, tier="sonnet")
    if not raw:
        raise ValueError("LLM returned empty response")

    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.split("```", 2)[-1]  # 取 ``` 後的內容
        if clean.startswith("json"):
            clean = clean[4:]
    if clean.endswith("```"):
        clean = clean[:-3]
    clean = clean.strip()

    data = json.loads(clean)

    # ── 安全預設值 ──────────────────────────────────────
    arch = data.get("archaeology") or {}
    triad = data.get("triad") or {}
    arc   = data.get("narrative_arc") or {}

    return {
        "summary":     data.get("summary", ""),
        "themes":      data.get("themes", []),
        "growth_note": data.get("growth_note", ""),
        "archaeology": {
            "surface": arch.get("surface", ""),
            "middle":  arch.get("middle",  ""),
            "deep":    arch.get("deep",    ""),
        },
        "triad": {
            "emotion":   triad.get("emotion",   []),
            "cognition": triad.get("cognition", []),
            "need":      triad.get("need",      []),
        },
        "narrative_arc": {
            "opening":     arc.get("opening",     ""),
            "development": arc.get("development", ""),
            "turning":     arc.get("turning",     ""),
            "closing":     arc.get("closing",     ""),
        },
        "end_quote":    data.get("end_quote",    ""),
        "quote_author": data.get("quote_author", ""),
    }

# ── 低參與降級塔羅池 ─────────────────────────────────────
_LOW_ENGAGEMENT_TAROT_POOL = [
    ("WHEEL_OF_FORTUNE_REVERSED", "命運之輪・逆位", "靜待時機，內在正在蓄積力量"),
    ("HIGH_PRIESTESS", "女祭司", "沉默中自有深邃的智慧"),
    ("HERMIT",         "隱者",   "獨處是為了更清醒地回到自己"),
    ("MOON",           "月亮",   "在模糊之中，感受也是真實的"),
]

# ── 單一用戶週報建構 ──────────────────────────────────────
async def build_weekly_report(
    user_id: str, start: date, end: date, week_id: str
) -> Optional[dict]:

    messages   = await get_messages_in_range(user_id, start, end)
    psych_rows = await get_psych_in_range(user_id, start, end)

    # ── 低度參與（零訊息）降級週報 ─────────────────────
    if not messages:
        tarot_key, tarot_name, tarot_meaning = random.choice(_LOW_ENGAGEMENT_TAROT_POOL)
        fallback = {
            "week_id":           week_id,
            "user_id":           user_id,
            "start":             start.isoformat(),
            "end":               end.isoformat(),
            "summary":           "這週的你選擇把心事暫時闔上，給了自己一段安靜沉澱的空間。這也是很棒的自我調節方式。",
            "themes":            [],
            "growth_note":       "在無言的留白中，內心正在靜靜蓄積重新出發的能量。",
            "end_quote":         "有時候，什麼都不說，也是一種對自己的溫柔。",
            "raw_count":         0,
            "created_at":        datetime.utcnow().isoformat(),
            "is_low_engagement": True,
            "archaeology": {"surface": "", "middle": "", "deep": ""},
            "triad": {"emotion": [], "cognition": [], "need": []},
            "narrative_arc": {
                "opening": "", "development": "", "turning": "", "closing": "",
            },
            "psych_context": {
                "dialogue_insight": "在無言的留白中，內心正在靜靜蓄積重新出發的能量。",
                "tarot_card":       tarot_key,
                "tarot_name_zh":    tarot_name,
                "tarot_meaning":    tarot_meaning,
                "end_quote":        "有時候，什麼都不說，也是一種對自己的溫柔。",
                "quote_author":     "心事日記",
            },
            "stats": {
                "total_turns": 0, "user_msg_count": 0,
                "avg_arousal": None, "arousal_curve": [],
                "emotion_counts": {}, "daily_counts": {},
                "past_baseline": None,
            },
        }
        try:
            await save_archive(
                user_id, week_id, fallback["summary"],
                stats={**fallback["stats"],
                       "themes": [], "growth_note": fallback["growth_note"],
                       "start": start.isoformat(), "end": end.isoformat(),
                       "is_low_engagement": True},
                raw_count=0,
            )
        except Exception as e:
            print(f"[weekly] save_archive (low-eng) failed {user_id}: {e}")
        try:
            await put_weekly_report(user_id, week_id, fallback)
        except Exception:
            pass
        print(f"[weekly] {user_id} {week_id}: no messages → low-engagement report")
        return fallback

    # ── 本地統計 ─────────────────────────────────────────
    stats = compute_stats(messages, psych_rows)

    # past_baseline：從本週 arousal_curve 計算移動平均作為基準線
    # （真實上週曲線需從 archives 取出，此處使用同週平滑版本作近似）
    arousals = [p["v"] for p in stats["arousal_curve"]]
    if len(arousals) >= 3:
        window = max(2, len(arousals) // 4)
        baseline = []
        for i in range(len(arousals)):
            lo  = max(0, i - window)
            avg = round(sum(arousals[lo:i + 1]) / (i - lo + 1), 2)
            baseline.append({"t": stats["arousal_curve"][i]["t"], "v": avg})
        stats["past_baseline"] = baseline
    else:
        stats["past_baseline"] = None

    # ── AI 情感考古 ───────────────────────────────────────
    arch_result: dict = {}
    try:
        arch_result = await generate_archaeology_report(messages, psych_rows, week_id)
    except Exception as e:
        print(f"[weekly] archaeology AI failed {user_id} {week_id}: {e}")
        arch_result = {
            "summary":       "本週摘要生成失敗，但統計資料仍完整。",
            "themes":        [],
            "growth_note":   "",
            "archaeology":   {"surface": "", "middle": "", "deep": ""},
            "triad":         {"emotion": [], "cognition": [], "need": []},
            "narrative_arc": {"opening": "", "development": "", "turning": "", "closing": ""},
            "end_quote":     "",
            "quote_author":  "",
        }

    # ── 從 psych_rows 提取 psych_context（最後一筆完整資料）───
    pc_end_quote = arch_result.get("end_quote") or None
    pc_author    = arch_result.get("quote_author") or None
    pc_insight   = None
    pc_tarot     = None
    pc_tarot_name = None
    pc_tarot_meaning = None

    for row in reversed(psych_rows):
        if row.get("dialogue_insight") and not pc_insight:
            pc_insight = row["dialogue_insight"]
        if row.get("tarot_card") and not pc_tarot:
            pc_tarot      = row["tarot_card"]
            pc_tarot_name = row.get("tarot_name_zh") or row.get("tarot_card")
            pc_tarot_meaning = row.get("tarot_meaning", "")
        if row.get("end_quote") and not pc_end_quote:
            pc_end_quote = row["end_quote"]
        if row.get("quote_author") and not pc_author:
            pc_author = row["quote_author"]
        if all([pc_insight, pc_tarot, pc_end_quote, pc_author]):
            break

    report = {
        "week_id":    week_id,
        "user_id":    user_id,
        "start":      start.isoformat(),
        "end":        end.isoformat(),
        "summary":    arch_result["summary"],
        "themes":     arch_result["themes"],
        "growth_note": arch_result["growth_note"],
        "archaeology":   arch_result["archaeology"],
        "triad":         arch_result["triad"],
        "narrative_arc": arch_result["narrative_arc"],
        "end_quote":     arch_result.get("end_quote") or pc_end_quote,
        "stats":         stats,
        "raw_count":     len(messages),
        "created_at":    datetime.utcnow().isoformat(),
        "psych_context": {
            "dialogue_insight": pc_insight,
            "tarot_card":       pc_tarot,
            "tarot_name_zh":    pc_tarot_name,
            "tarot_meaning":    pc_tarot_meaning,
            "end_quote":        arch_result.get("end_quote") or pc_end_quote,
            "quote_author":     arch_result.get("quote_author") or pc_author,
        },
    }

    # ── 寫入 PostgreSQL（永久）───────────────────────────
    try:
        await save_archive(
            user_id, week_id, report["summary"],
            stats={
                **stats,
                "themes":        report["themes"],
                "growth_note":   report["growth_note"],
                "archaeology":   report["archaeology"],
                "triad":         report["triad"],
                "narrative_arc": report["narrative_arc"],
                "start":         start.isoformat(),
                "end":           end.isoformat(),
                "end_quote":     report["end_quote"],
                "quote_author":  report["psych_context"]["quote_author"],
                "dialogue_insight": pc_insight,
                "tarot_card":       pc_tarot,
                "tarot_name_zh":    pc_tarot_name,
                "tarot_meaning":    pc_tarot_meaning,
            },
            raw_count=len(messages),
        )
    except Exception as e:
        print(f"[weekly] save_archive failed {user_id} {week_id}: {e}")

    # ── 寫入 Redis（TTL 30 天，前端即時 pop）─────────────
    try:
        await put_weekly_report(user_id, week_id, report)
    except Exception:
        pass

    # ── 刪除原始訊息 ─────────────────────────────────────
    try:
        deleted = await delete_messages_in_range(user_id, start, end)
        print(f"[weekly] {user_id} {week_id}: {deleted} msgs deleted, report saved")
    except Exception as e:
        print(f"[weekly] delete_messages failed {user_id}: {e}")

    return report

# ── 公開介面 ─────────────────────────────────────────────
async def generate_weekly_report(user_id: str) -> Optional[dict]:
    """
    公開介面：為指定用戶生成上週的情感考古週報。
    完整走 PostgreSQL 寫入 + Redis 快取 + 刪除原始訊息的閉環邏輯。
    """
    start, end, week_id = get_last_week_range()
    return await build_weekly_report(user_id, start, end, week_id)

# ── 全量排程入口 ──────────────────────────────────────────
async def run_weekly_archive() -> None:
    """
    Railway Cron：0 19 * * 0（UTC 週日 19:00 = 台灣週一凌晨 3:00）
    """
    start, end, week_id = get_last_week_range()
    print(f"[weekly] Processing {week_id} ({start} ~ {end})")

    users = await get_users_in_range(start, end)
    print(f"[weekly] {len(users)} users to process")

    sem = asyncio.Semaphore(5)

    async def safe_build(uid: str):
        async with sem:
            try:
                await build_weekly_report(uid, start, end, week_id)
            except Exception as e:
                print(f"[weekly] Error {uid}: {e}")

    await asyncio.gather(*[safe_build(u) for u in users])
    print(f"[weekly] Done: {week_id}")

if __name__ == "__main__":
    asyncio.run(run_weekly_archive())
