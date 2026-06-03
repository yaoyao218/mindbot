import os
import hashlib
import hmac
import base64
import httpx
from typing import Optional
from fastapi import FastAPI, Request, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from linebot.v3 import WebhookParser
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent, PostbackEvent, FollowEvent
)
from handlers.message import handle_message
from handlers.postback import handle_postback

app = FastAPI()

# 掛載靜態檔案目錄
import os as _os
if _os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def startup():
    # DB 初始化
    try:
        from services.db_persistent import init_db
        await init_db()
    except Exception as e:
        print(f"[Startup] DB init skipped (memory mode): {e}")

    # 排程（APScheduler）
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from services.weekly_scheduler import run_weekly_archive

        scheduler = AsyncIOScheduler(timezone="Asia/Taipei")

        # 週一 03:00 台灣時間 = UTC 週日 19:00
        scheduler.add_job(run_weekly_archive, "cron",
                          day_of_week="sun", hour=19, minute=0)

        # P0-A 今日一問：每分鐘檢查是否有用戶的推播時間到了
        async def _daily_question_job():
            try:
                from services.daily_question import run_daily_question_scheduler
                with ApiClient(configuration) as api_client:
                    _api = MessagingApi(api_client)
                    await run_daily_question_scheduler(_api)
            except Exception as e:
                print(f"[DailyQ Scheduler] Error: {e}")

        scheduler.add_job(_daily_question_job, "cron", minute="*")

        # P2-B LINE 週報 LINE 推播：每週一凌晨 3:05（週報生成完後）
        async def _weekly_line_push_job():
            try:
                from services.line_weekly_push import push_weekly_reports_to_line
                with ApiClient(configuration) as api_client:
                    _api = MessagingApi(api_client)
                    await push_weekly_reports_to_line(_api)
            except Exception as e:
                print(f"[WeeklyPush] Error: {e}")

        scheduler.add_job(_weekly_line_push_job, "cron",
                          day_of_week="sun", hour=19, minute=5)

        scheduler.start()
        print("[Startup] Scheduler started (weekly + daily question + weekly push)")
    except Exception as e:
        print(f"[Startup] Scheduler skipped: {e}")


# ── LINE Bot 設定 ─────────────────────────────────────────
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(CHANNEL_SECRET)


def verify_signature(body: bytes, signature: str) -> bool:
    """保留供外部呼叫，實際驗證由 parser.parse 處理"""
    try:
        hash_val = hmac.new(
            CHANNEL_SECRET.encode("utf-8"),
            body,
            hashlib.sha256
        ).digest()
        expected = base64.b64encode(hash_val).decode("utf-8")
        return hmac.compare_digest(expected, signature)
    except Exception:
        return False


async def process_line_events(events: list) -> None:
    """BackgroundTask：非同步處理 LINE 事件，不佔用 webhook 回應時間"""
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        for event in events:
            try:
                if isinstance(event, MessageEvent) and \
                   isinstance(event.message, TextMessageContent):
                    await handle_message(event, line_bot_api)
                elif isinstance(event, PostbackEvent):
                    await handle_postback(event, line_bot_api)
                elif isinstance(event, FollowEvent):
                    from handlers.onboarding import send_welcome
                    await send_welcome(event.source.user_id, line_bot_api)
            except Exception as e:
                print(f"[Webhook] Event processing error: {e}")


# ── 健康檢查 ─────────────────────────────────────────────

@app.get("/")
async def health_check():
    return {"status": "MindBot is running 🤖"}


# ── 前端 SPA ─────────────────────────────────────────────

@app.get("/app")
async def serve_app():
    """心事日記 Web App 主頁（舊版 prototype.html）"""
    return FileResponse("static/prototype.html")


@app.get("/app-v2")
async def serve_app_v2():
    """心事日記 Web App v2（模組化 LIFF SPA）"""
    return FileResponse("static/public/index.html")


@app.get("/callback")
async def oauth_callback():
    """LINE Login OAuth redirect → 回到 SPA 由前端處理 code"""
    # v2 LIFF 不走此路徑（LIFF 直接 redirect 回 /app-v2）
    return FileResponse("static/prototype.html")


def _make_session_token(user_id: str, display_name: str) -> str:
    """
    產生 HMAC 簽名的 session token：
    格式 base64(user_id:display_name:expires):signature
    不需要 server-side storage
    """
    import time, json
    expires = int(time.time()) + 86400 * 30   # 30 天
    payload = f"{user_id}|{display_name}|{expires}"
    sig = hmac.new(
        CHANNEL_SECRET.encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()[:16]
    return base64.urlsafe_b64encode(
        f"{payload}|{sig}".encode()
    ).decode().rstrip("=")


def _verify_session_token(token: str) -> Optional[str]:
    """驗證 session token，回傳 user_id 或 None"""
    import time
    try:
        padded = token + "=" * (4 - len(token) % 4)
        decoded = base64.urlsafe_b64decode(padded).decode()
        parts = decoded.split("|")
        if len(parts) != 4:
            return None
        user_id, display_name, expires_str, sig = parts
        if int(expires_str) < time.time():
            return None
        payload = f"{user_id}|{display_name}|{expires_str}"
        expected_sig = hmac.new(
            CHANNEL_SECRET.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected_sig):
            return None
        return user_id
    except Exception:
        return None


@app.get("/auto-login")
async def auto_login(t: str = ""):
    """
    Bot 發送的一次性登入連結
    ?t=TOKEN → 驗證 → 產生 session token → 導向 /app
    """
    from fastapi.responses import HTMLResponse
    from services.login_token import consume_token

    user_id = consume_token(t) if t else None
    if not user_id:
        return HTMLResponse(
            '<html><head><meta charset="utf-8"></head>'
            '<body style="font-family:sans-serif;text-align:center;padding:60px 20px">'
            '<h2>🔗 連結已失效</h2>'
            '<p style="color:#999;font-size:14px">請回到 LINE 重新傳送「登入」取得新連結</p>'
            '</body></html>',
            status_code=400
        )

    # 取得 LINE 用戶名稱
    display_name = "用戶"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"https://api.line.me/v2/bot/profile/{user_id}",
                headers={"Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"},
            )
            if r.status_code == 200:
                display_name = r.json().get("displayName", "用戶")
    except Exception:
        pass

    session_token = _make_session_token(user_id, display_name)
    name_enc = base64.urlsafe_b64encode(display_name.encode()).decode().rstrip("=")

    return HTMLResponse(
        f'<html><head><meta charset="utf-8">'
        f'<script>'
        f'localStorage.setItem("mb_token","{session_token}");'
        f'localStorage.setItem("mb_user_id","{user_id}");'
        f'localStorage.setItem("mb_name","{display_name}");'
        f'location.replace("/app");'
        f'</script>'
        f'</head><body>登入中…</body></html>'
    )


@app.get("/calendar")
async def serve_calendar():
    """情緒月曆入口（從 LINE 連結過來）→ 帶 hash 導向 SPA"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        '<html><head>'
        '<meta http-equiv="refresh" content="0; url=/app#calendar">'
        '<script>location.replace("/app#calendar")</script>'
        '</head></html>'
    )


@app.get("/report")
async def serve_report():
    """週報入口（從 LINE 連結過來）→ 帶 hash 導向 SPA"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        '<html><head>'
        '<meta http-equiv="refresh" content="0; url=/app#weeks">'
        '<script>location.replace("/app#weeks")</script>'
        '</head></html>'
    )


# ── 前端設定（注入環境變數給 SPA）────────────────────────

@app.get("/api/config")
async def get_config():
    """前端啟動時呼叫，取得 LINE Login Channel ID、LIFF ID 等設定"""
    return JSONResponse({
        "line_login_channel_id": os.environ.get("LINE_LOGIN_CHANNEL_ID", ""),
        "liff_id":               os.environ.get("LIFF_ID", ""),          # 有設定才啟用 LIFF
        "app_url":               os.environ.get("APP_URL", "https://web-production-dd506.up.railway.app"),
    })


# ── Webhook（立刻回 200，非同步處理）─────────────────────

@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    body      = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    # 診斷日誌（可在 Railway 的 Logs 看到）
    secret_set = bool(CHANNEL_SECRET)
    sig_len    = len(signature)
    body_len   = len(body)
    print(f"[Webhook] secret_set={secret_set} sig_len={sig_len} body_len={body_len}")

    if not secret_set:
        print("[Webhook] ERROR: LINE_CHANNEL_SECRET is not set!")
        raise HTTPException(status_code=500, detail="Server configuration error")

    # 用 LINE SDK 一次完成驗證 + 解析（避免雙重驗證衝突）
    try:
        events = parser.parse(body.decode("utf-8"), signature)
    except Exception as e:
        err_msg = str(e)
        print(f"[Webhook] Parse/verify error: {err_msg}")
        # InvalidSignatureError → 400；其他解析錯誤也回 400
        raise HTTPException(status_code=400, detail=err_msg)

    background_tasks.add_task(process_line_events, events)
    return JSONResponse(content={"status": "ok"})


# ── LINE Login 驗證（Bearer token → user_id）─────────────

async def get_current_user(request: Request) -> str:
    """
    驗證身份，回傳 user_id
    接受兩種 token：
      1. 我們自己簽發的 session token（/auto-login 流程）
      2. LINE access token（LINE OAuth 流程）
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth[7:]

    # 先嘗試我們自己的 session token（快，不需要外部請求）
    user_id = _verify_session_token(token)
    if user_id:
        return user_id

    # fallback：LINE access token 驗證
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.line.me/v2/profile",
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.status_code == 200:
            return r.json()["userId"]
    except Exception:
        pass

    raise HTTPException(status_code=401, detail="Invalid token")


# ── LINE Login Callback ───────────────────────────────────

@app.post("/api/auth/line_callback")
async def line_callback(request: Request):
    """
    前端登入回呼，支援兩種模式：
      1. LINE OAuth（傳統）：body { code, redirect_uri }
      2. LIFF：body { liff_token }  → 直接驗證 access token，跳過 code exchange
    response: { token, user_id, name }
    """
    body = await request.json()

    # ── LIFF 模式：直接驗證 access token ─────────────────
    liff_token = body.get("liff_token")
    if liff_token:
        async with httpx.AsyncClient(timeout=10) as client:
            profile_r = await client.get(
                "https://api.line.me/v2/profile",
                headers={"Authorization": f"Bearer {liff_token}"},
            )
        if profile_r.status_code != 200:
            raise HTTPException(status_code=401, detail="LIFF token invalid")
        profile = profile_r.json()
        # 簽發我們自己的 session token（讓後續 API 呼叫不需要一直打 LINE）
        from services.login_token import create_token
        our_token = create_token(profile["userId"])
        return JSONResponse({
            "token":   our_token,
            "user_id": profile["userId"],
            "name":    profile.get("displayName", ""),
        })

    # ── LINE OAuth 模式（傳統）────────────────────────────
    code = body.get("code")
    redirect_uri = body.get("redirect_uri")

    client_id     = os.environ.get("LINE_LOGIN_CHANNEL_ID", "")
    client_secret = os.environ.get("LINE_LOGIN_CHANNEL_SECRET", "")
    print(f"[LineCallback] client_id={client_id[:4]}… redirect_uri={redirect_uri}")

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            "https://api.line.me/oauth2/v2.1/token",
            data={
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  redirect_uri,
                "client_id":     client_id,
                "client_secret": client_secret,
            },
        )

    if r.status_code != 200:
        err = r.text[:200]
        print(f"[LineCallback] Token exchange failed {r.status_code}: {err}")
        raise HTTPException(
            status_code=400,
            detail=f"Token exchange failed: {r.status_code} {err}"
        )

    access_token = r.json()["access_token"]

    async with httpx.AsyncClient(timeout=10) as client:
        profile_r = await client.get(
            "https://api.line.me/v2/profile",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    profile = profile_r.json()

    return JSONResponse({
        "token":        access_token,
        "user_id":      profile["userId"],
        "display_name": profile.get("displayName", ""),
    })


# ── 環境變數 + 連線診斷 ──────────────────────────────────

@app.get("/api/health")
async def health_detail():
    """完整診斷：環境變數是否齊全"""
    import os
    def masked(key):
        v = os.environ.get(key, "")
        if not v: return "❌ 未設定"
        return f"✅ {v[:6]}…（長度 {len(v)}）"

    try:
        from services.llm import _provider
        llm = _provider()
    except Exception as e:
        llm = f"error: {e}"

    # 驗證 webhook 簽章是否可正常運作
    test_body = b'{"destination":"test","events":[]}'
    import hmac as _hmac, hashlib as _hashlib, base64 as _base64
    try:
        secret = CHANNEL_SECRET.encode("utf-8")
        test_sig = _base64.b64encode(
            _hmac.new(secret, test_body, _hashlib.sha256).digest()
        ).decode("utf-8")
        sig_ok = verify_signature(test_body, test_sig)
    except Exception as e:
        sig_ok = f"error: {e}"

    # 測試 DB 連線
    db_status = "❌ 未設定"
    if os.environ.get("DATABASE_URL"):
        try:
            from services.db_persistent import get_pool
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            db_status = "✅ 連線成功"
        except Exception as e:
            db_status = f"❌ 連線失敗: {str(e)[:60]}"

    return JSONResponse({
        "server": "ok",
        "llm_provider": llm,
        "webhook_signature_test": sig_ok,
        "channel_secret_length": len(CHANNEL_SECRET),
        "database": db_status,
        "env": {
            "LINE_CHANNEL_SECRET":       masked("LINE_CHANNEL_SECRET"),
            "LINE_CHANNEL_ACCESS_TOKEN": masked("LINE_CHANNEL_ACCESS_TOKEN"),
            "LINE_LOGIN_CHANNEL_ID":     masked("LINE_LOGIN_CHANNEL_ID"),
            "LINE_LOGIN_CHANNEL_SECRET": masked("LINE_LOGIN_CHANNEL_SECRET"),
            "GROQ_API_KEY":              masked("GROQ_API_KEY"),
            "ANTHROPIC_API_KEY":         masked("ANTHROPIC_API_KEY"),
            "DATABASE_URL":              masked("DATABASE_URL"),
            "REDIS_URL":                 masked("REDIS_URL"),
        }
    })


@app.get("/api/llm-test")
async def llm_test():
    """測試 Groq / Anthropic 是否正確連線"""
    import os
    from services.llm import call_api, _provider
    provider = _provider()
    key_set = bool(os.environ.get("GROQ_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))
    try:
        reply = await call_api("請用繁體中文回答：1+1=？只回答數字即可。", max_tokens=10)
        return JSONResponse({
            "provider": provider,
            "key_set": key_set,
            "reply": reply,
            "ok": bool(reply),
        })
    except Exception as e:
        return JSONResponse({
            "provider": provider,
            "key_set": key_set,
            "error": str(e),
            "ok": False,
        }, status_code=500)


# ── 前端同步 API ──────────────────────────────────────────

@app.get("/api/sync/conversations")
async def sync_conversations(user_id: str = Depends(get_current_user)):
    """
    拉取對話緩衝區：優先 Redis，fallback 到 in-process buffer
    response: { messages: Message[], count: int }
    """
    messages = []
    # 嘗試 Redis
    try:
        from services.redis_client import pop_buffered_messages
        messages = await pop_buffered_messages(user_id)
    except Exception:
        pass

    # Redis 無資料或未設定 → 用 in-process buffer
    if not messages:
        try:
            from services import message_buffer
            messages = message_buffer.get(user_id)
        except Exception:
            pass

    return JSONResponse({"messages": messages, "count": len(messages)})


@app.get("/api/conversations")
async def get_conversations(
    limit: int = 100,
    user_id: str = Depends(get_current_user),
):
    """
    取得用戶的完整對話紀錄（用於網站初次載入）
    優先從 DB，fallback 到 in-process buffer
    """
    messages = []

    # 嘗試 DB（asyncpg / PostgreSQL）
    try:
        from services.db_persistent import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT role, content, created_at
                FROM session_messages
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                user_id, limit
            )
            messages = list(reversed([
                {
                    "role":       r["role"],
                    "content":    r["content"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else "",
                }
                for r in rows
            ]))
    except Exception as e:
        print(f"[conversations] DB error: {e}")

    # Fallback: in-process buffer
    if not messages:
        try:
            from services import message_buffer
            msgs = message_buffer.get(user_id)
            messages = msgs[-limit:]
        except Exception:
            pass

    return JSONResponse({"messages": messages, "count": len(messages)})


@app.get("/api/snapshot")
async def get_snapshot(user_id: str = Depends(get_current_user)):
    """
    本週即時快照 — 直接從 PostgreSQL 計算，不依賴 Redis
    回傳格式與 weekly report 相容
    """
    from datetime import date as _date, timedelta
    from services.weekly_scheduler import (
        get_week_id, compute_stats, generate_weekly_summary
    )
    from services.db_persistent import (
        get_messages_in_range, get_psych_in_range, get_pool, get_emotion_calendar
    )

    today    = _date.today()
    mon      = today - timedelta(days=today.weekday())   # 本週一
    sun      = mon + timedelta(days=6)                   # 本週日
    week_id  = get_week_id(mon)

    try:
        # 查詢到今天為止的資料（週日前持續累積）
        messages   = await get_messages_in_range(user_id, mon, today)
        psych_rows = await get_psych_in_range(user_id, mon, today)

        if not messages:
            return JSONResponse({
                "empty":   True,
                "week_id": week_id,
                "start":   mon.isoformat(),
                "end":     sun.isoformat(),
                "is_current_week": True,
            })

        stats = compute_stats(messages, psych_rows)

        # AI 摘要（快取到 archives，避免每次都呼叫）
        pool = await get_pool()
        async with pool.acquire() as conn:
            cached = await conn.fetchrow(
                "SELECT summary, stats FROM archives WHERE user_id=$1 AND year_month=$2",
                user_id, week_id
            )

        import time as _time
        now_ts = _time.time()

        # 快取邏輯：6 小時內不重算，讓摘要每天能反映最新狀態
        SUMMARY_TTL = 6 * 3600
        cache_ok = False
        if cached and cached["summary"]:
            cs = dict(cached["stats"]) if cached["stats"] else {}
            cached_at = cs.get("summary_cached_at", 0)
            if now_ts - float(cached_at) < SUMMARY_TTL:
                summary     = cached["summary"]
                themes      = cs.get("themes", [])
                growth_note = cs.get("growth_note", "")
                cache_ok    = True

        if not cache_ok:
            try:
                summary, themes, growth_note = await generate_weekly_summary(
                    messages, week_id
                )
                from services.db_persistent import save_archive
                await save_archive(
                    user_id, week_id, summary,
                    stats={**stats, "themes": themes, "growth_note": growth_note,
                           "start": mon.isoformat(), "end": sun.isoformat(),
                           "summary_cached_at": str(now_ts)},
                    raw_count=len(messages),
                )
            except Exception as e:
                print(f"[snapshot] AI summary failed: {e}")
                summary = ""; themes = []; growth_note = ""

        # 本週代表牌：從 emotion_calendar 取最新有塔羅的記錄
        week_tarot     = None
        week_end_quote = None
        psych_context  = {}
        try:
            cal_recs = await get_emotion_calendar(user_id, mon.year, mon.month)
            week_days = {(mon + timedelta(days=i)).isoformat() for i in range(7)}
            tarot_recs = [r for r in cal_recs if r.get("tarot_card") and r["record_date"] in week_days]
            if tarot_recs:
                latest = sorted(tarot_recs, key=lambda x: x["record_date"])[-1]
                week_tarot = {
                    "card":     latest["tarot_card"],
                    "meaning":  latest["tarot_meaning"],
                    "reversed": latest.get("tarot_reversed", False),
                }

            # 最近一筆含 psych_context 的收尾記錄（本週內）
            async with pool.acquire() as conn:
                pc_row = await conn.fetchrow(
                    """SELECT end_quote, dialogue_insight, quote_author, tarot_card
                       FROM session_psych
                       WHERE user_id=$1 AND created_at::date >= $2
                         AND (end_quote IS NOT NULL OR dialogue_insight IS NOT NULL)
                       ORDER BY created_at DESC LIMIT 1""",
                    user_id, mon
                )
            if pc_row:
                week_end_quote = pc_row["end_quote"]
                tarot_key      = pc_row["tarot_card"]
                tarot_name     = None
                if tarot_key:
                    try:
                        from services.tarot_quotes_pool import TAROT_POOL
                        tarot_name = TAROT_POOL.get(tarot_key, {}).get("name_zh")
                    except Exception:
                        pass
                psych_context = {
                    "dialogue_insight": pc_row["dialogue_insight"],
                    "tarot_card":       tarot_key,
                    "tarot_name_zh":    tarot_name,
                    "end_quote":        pc_row["end_quote"],
                    "quote_author":     pc_row["quote_author"],
                }
        except Exception:
            pass

        return JSONResponse({
            "week_id":         week_id,
            "start":           mon.isoformat(),
            "end":             sun.isoformat(),
            "today":           today.isoformat(),
            "summary":         summary,
            "themes":          themes,
            "growth_note":     growth_note,
            "stats":           stats,
            "raw_count":       len([m for m in messages if m["role"] == "user"]),
            "empty":           False,
            "is_current_week": True,
            "week_tarot":      week_tarot,
            "end_quote":       week_end_quote,
            "psych_context":   psych_context,
        })
    except Exception as e:
        print(f"[snapshot] error: {e}")
        return JSONResponse({"empty": True, "week_id": week_id, "error": str(e)})


@app.get("/api/milestones")
async def get_milestones_api(user_id: str = Depends(get_current_user)):
    """
    取得用戶里程碑資料：
    - 對話天數、連續天數
    - 已觸發的里程碑（含 AI 觀察文字）
    - 最近 14 天 emoji 序列（月曆觀察用）
    """
    from datetime import date as _date, timedelta
    today = _date.today()

    conv_days = 0
    streak    = 0
    achieved  = []
    emoji_seq = []

    try:
        from services.db_persistent import (
            count_conversation_days, get_streak_days,
            get_user_milestones, get_emotion_calendar, get_pool
        )
        conv_days = await count_conversation_days(user_id)
        streak    = await get_streak_days(user_id)
        achieved  = await get_user_milestones(user_id)

        # 最近 14 天 emoji
        for delta in range(13, -1, -1):
            d = today - timedelta(days=delta)
            recs = await get_emotion_calendar(user_id, d.year, d.month)
            day_str = d.isoformat()
            found = next((r for r in recs if r["record_date"] == day_str), None)
            emoji_seq.append({
                "date":  day_str,
                "emoji": found["emotion_emoji"] if found else None,
            })
    except Exception as e:
        print(f"[milestones API] {e}")

    return JSONResponse({
        "conv_days": conv_days,
        "streak":    streak,
        "achieved":  achieved,
        "emoji_14d": emoji_seq,
    })


@app.get("/api/emotion-calendar")
async def emotion_calendar(
    year: Optional[int] = None,
    month: Optional[int] = None,
    user_id: str = Depends(get_current_user),
):
    """取得情緒月曆資料（P2-A）"""
    from datetime import date as _date
    today = _date.today()
    y = year or today.year
    m = month or today.month
    try:
        from services.db_persistent import get_emotion_calendar, get_streak_days
        records = await get_emotion_calendar(user_id, y, m)
        streak = await get_streak_days(user_id)
        return JSONResponse({
            "year": y, "month": m,
            "records": records,
            "streak": streak,
        })
    except Exception as e:
        return JSONResponse({"records": [], "streak": 0, "error": str(e)})


@app.get("/api/daily-record")
async def get_daily_record_api(
    date: Optional[str] = None,
    user_id: str = Depends(get_current_user),
):
    """
    取得（或懶生成）某天的完整日記錄：
    情緒 + 塔羅牌 + AI 敘述
    date: YYYY-MM-DD，預設今天
    """
    from datetime import date as _date
    try:
        target = _date.fromisoformat(date) if date else _date.today()
    except ValueError:
        return JSONResponse({"error": "invalid date format"}, status_code=400)

    try:
        from services.daily_narrative import get_or_generate_narrative
        record = await get_or_generate_narrative(user_id, target)
        return JSONResponse(record)
    except Exception as e:
        return JSONResponse({"error": str(e), "found": False}, status_code=500)


@app.post("/api/push-schedule")
async def set_push_schedule_api(
    request: Request,
    user_id: str = Depends(get_current_user),
):
    """設定今日一問推播時間（P0-A）"""
    body = await request.json()
    hour = int(body.get("hour", 21))
    minute = int(body.get("minute", 0))
    enabled = bool(body.get("enabled", True))
    try:
        from services.daily_question import set_push_schedule
        from services.db_persistent import get_pool
        await set_push_schedule(user_id, hour, minute)
        if not enabled:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE push_schedule SET enabled = 0 WHERE user_id = $1",
                    user_id
                )
        return JSONResponse({"ok": True, "hour": hour, "minute": minute, "enabled": enabled})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/sync/weekly")
async def sync_weekly(
    since: Optional[str] = None,
    user_id: str = Depends(get_current_user),
):
    """
    增量拉取週報（Cache-First / PostgreSQL SSOT）

    流程：
      1. PostgreSQL archives 為 Single Source of Truth，先查出所有週報 ID
      2. 每份週報先嘗試 Redis cache（GET，不刪除）
      3. Cache miss → 查 PostgreSQL → 回寫 Redis cache（SETEX 30天）
      4. 永遠不 POP/DELETE Redis，快取過期自動失效
    """
    from services.db_persistent import get_weekly_reports
    reports: list[dict] = []

    # Step 1: PostgreSQL 為 SSOT，取出完整週報列表
    try:
        db_reports = await get_weekly_reports(user_id, since=since or "")
    except Exception as e:
        print(f"[sync_weekly] PostgreSQL error: {e}")
        return JSONResponse({"reports": [], "count": 0, "has_more": False})

    if not db_reports:
        return JSONResponse({"reports": [], "count": 0, "has_more": False})

    # Step 2+3: 逐份週報，優先讀 Redis cache，miss 則查 PG 並回寫
    try:
        from services.redis_client import get_weekly_report_cache, set_weekly_report_cache
        redis_ok = True
    except Exception:
        redis_ok = False

    for db_report in db_reports:
        wid = db_report["week_id"]
        report = None

        if redis_ok:
            try:
                report = await get_weekly_report_cache(user_id, wid)
            except Exception:
                pass

        if report is None:
            # Cache miss：使用 PostgreSQL 資料，並非同步回寫快取
            report = db_report
            if redis_ok:
                try:
                    await set_weekly_report_cache(user_id, wid, report)
                except Exception:
                    pass

        reports.append(report)

    return JSONResponse({
        "reports":  reports,
        "count":    len(reports),
        "has_more": False,
    })
