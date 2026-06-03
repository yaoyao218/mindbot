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
    """心事日記 Web App 主頁"""
    return FileResponse("static/prototype.html")


@app.get("/callback")
async def oauth_callback():
    """LINE Login OAuth redirect → 回到 SPA 由前端處理 code"""
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
    """前端啟動時呼叫，取得 LINE Login Channel ID 等設定"""
    return JSONResponse({
        "line_login_channel_id": os.environ.get("LINE_LOGIN_CHANNEL_ID", ""),
        "app_url": os.environ.get("APP_URL", "https://web-production-dd506.up.railway.app"),
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
    前端用 LINE Login code 換取 access token
    body: { code, redirect_uri }
    response: { token, user_id, display_name }
    """
    body = await request.json()
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
    增量拉取週報，只回傳比 since 新的
    query: since=2025-W03（可選，上次拉到的 week_id）
    response: { reports: WeeklyReport[], count: int, has_more: bool }
    """
    try:
        from services.redis_client import (
            list_pending_weekly, pop_weekly_report, set_last_sync
        )
        week_ids = await list_pending_weekly(user_id)

        if since:
            week_ids = [w for w in week_ids if w > since]

        reports = []
        for week_id in week_ids:
            report = await pop_weekly_report(user_id, week_id)
            if report:
                reports.append(report)
                await set_last_sync(user_id, week_id)
    except Exception as e:
        print(f"[sync_weekly] Error: {e}")
        reports = []

    return JSONResponse({
        "reports":  reports,
        "count":    len(reports),
        "has_more": False,
    })
