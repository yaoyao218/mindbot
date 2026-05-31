import os
import hashlib
import hmac
import base64
import httpx
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from linebot.v3 import WebhookParser
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent, PostbackEvent
)
from handlers.message import handle_message
from handlers.postback import handle_postback

app = FastAPI()


@app.on_event("startup")
async def startup():
    try:
        from services.db_persistent import init_db
        await init_db()
    except Exception as e:
        print(f"[Startup] DB init skipped (memory mode): {e}")


# ── Line Bot 設定 ─────────────────────────────────────────
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


# ── Webhook ───────────────────────────────────────────────

@app.get("/")
async def health_check():
    return {"status": "MindBot is running 🤖"}


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    if not verify_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        events = parser.parse(body.decode("utf-8"), signature)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        for event in events:
            if isinstance(event, MessageEvent) and \
               isinstance(event.message, TextMessageContent):
                await handle_message(event, line_bot_api)
            elif isinstance(event, PostbackEvent):
                await handle_postback(event, line_bot_api)

    return JSONResponse(content={"status": "ok"})


# ── Line Login 驗證（Bearer token → user_id）─────────────

async def get_current_user(request: Request) -> str:
    """用 Line Access Token 驗證身份，回傳 user_id"""
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


# ── Line Login Callback ───────────────────────────────────

@app.post("/api/auth/line_callback")
async def line_callback(request: Request):
    """
    前端用 Line Login code 換取 access token
    body: { code, redirect_uri }
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

    token_data = r.json()
    access_token = token_data["access_token"]

    async with httpx.AsyncClient(timeout=10) as client:
        profile_r = await client.get(
            "https://api.line.me/v2/profile",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    user_id = profile_r.json()["userId"]

    return JSONResponse({"token": access_token, "user_id": user_id})


# ── 前端同步 API ──────────────────────────────────────────

@app.get("/api/sync/conversations")
async def sync_conversations(user_id: str = Depends(get_current_user)):
    """前端登入後拉取未同步的對話訊息"""
    try:
        from services.redis_client import pop_buffered_messages
        messages = await pop_buffered_messages(user_id)
    except Exception:
        messages = []
    return JSONResponse({"messages": messages})


@app.get("/api/sync/archives")
async def sync_archives(user_id: str = Depends(get_current_user)):
    """前端登入後拉取待領的月度摘要"""
    try:
        from services.redis_client import list_pending_archives, pop_archive
        year_months = await list_pending_archives(user_id)
        archives = []
        for ym in year_months:
            arch = await pop_archive(user_id, ym)
            if arch:
                archives.append(arch)
    except Exception:
        archives = []
    return JSONResponse({"archives": archives})
