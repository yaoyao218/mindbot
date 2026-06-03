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
    hash_val = hmac.new(
        CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256
    ).digest()
    expected = base64.b64encode(hash_val).decode("utf-8")
    return hmac.compare_digest(expected, signature)


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
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    if not verify_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        events = parser.parse(body.decode("utf-8"), signature)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    background_tasks.add_task(process_line_events, events)
    return JSONResponse(content={"status": "ok"})


# ── LINE Login 驗證（Bearer token → user_id）─────────────

async def get_current_user(request: Request) -> str:
    """用 LINE Access Token 驗證身份，回傳 user_id"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth[7:]
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            "https://api.line.me/v2/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid token")
    return r.json()["userId"]


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

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            "https://api.line.me/oauth2/v2.1/token",
            data={
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  redirect_uri,
                "client_id":     os.environ.get("LINE_LOGIN_CHANNEL_ID", ""),
                "client_secret": os.environ.get("LINE_LOGIN_CHANNEL_SECRET", ""),
            },
        )
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail="Token exchange failed")

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

    from services.llm import _provider
    return JSONResponse({
        "server": "ok",
        "llm_provider": _provider(),
        "env": {
            "LINE_CHANNEL_SECRET":       masked("LINE_CHANNEL_SECRET"),
            "LINE_CHANNEL_ACCESS_TOKEN": masked("LINE_CHANNEL_ACCESS_TOKEN"),
            "LINE_LOGIN_CHANNEL_ID":     masked("LINE_LOGIN_CHANNEL_ID"),
            "LINE_LOGIN_CHANNEL_SECRET": masked("LINE_LOGIN_CHANNEL_SECRET"),
            "GROQ_API_KEY":              masked("GROQ_API_KEY"),
            "ANTHROPIC_API_KEY":         masked("ANTHROPIC_API_KEY"),
            "REDIS_URL":                 masked("REDIS_URL"),
            "DB_HOST":                   masked("DB_HOST"),
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
    拉取 Redis 對話緩衝區（原子 pop，不重複）
    response: { messages: Message[], count: int }
    """
    try:
        from services.redis_client import pop_buffered_messages
        messages = await pop_buffered_messages(user_id)
    except Exception:
        messages = []
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
                async with conn.cursor() as cur:
                    await cur.execute(
                        "UPDATE push_schedule SET enabled = 0 WHERE user_id = %s",
                        (user_id,)
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
