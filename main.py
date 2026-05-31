import os
import hashlib
import hmac
import base64
from fastapi import FastAPI, Request, HTTPException
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
        print(f"[Startup] DB init skipped (will use memory session): {e}")

# 設定
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(CHANNEL_SECRET)


def verify_signature(body: bytes, signature: str) -> bool:
    """驗證 Line Webhook 簽章"""
    hash_val = hmac.new(
        CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256
    ).digest()
    expected = base64.b64encode(hash_val).decode("utf-8")
    return hmac.compare_digest(expected, signature)


@app.get("/")
async def health_check():
    return {"status": "MindBot is running 🤖"}


@app.post("/webhook")
async def webhook(request: Request):
    # 取得請求內容
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    # 驗證簽章
    if not verify_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 解析事件
    try:
        events = parser.parse(body.decode("utf-8"), signature)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 處理每個事件
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        for event in events:
            # 文字訊息
            if isinstance(event, MessageEvent) and \
               isinstance(event.message, TextMessageContent):
                await handle_message(event, line_bot_api)

            # 按鈕回應（Postback）
            elif isinstance(event, PostbackEvent):
                await handle_postback(event, line_bot_api)

    return JSONResponse(content={"status": "ok"})
