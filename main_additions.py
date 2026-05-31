"""
新增至 main.py 的端點與啟動設定
"""
import os
from fastapi import FastAPI, Request, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx

from services.db_persistent import init_db
from services.redis_client import (
    pop_buffered_messages,
    list_pending_weekly,
    pop_weekly_report,
    get_last_sync,
    set_last_sync,
)

# ── 掛載靜態檔案 ──────────────────────────────────────────
# app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Startup ───────────────────────────────────────────────
# @app.on_event("startup")
# async def startup():
#     await init_db()
#     # APScheduler 週排程
#     from apscheduler.schedulers.asyncio import AsyncIOScheduler
#     from services.weekly_scheduler import run_weekly_archive
#     scheduler = AsyncIOScheduler(timezone="Asia/Taipei")
#     scheduler.add_job(run_weekly_archive, "cron", day_of_week="mon", hour=3, minute=0)
#     scheduler.start()

# ── Auth ──────────────────────────────────────────────────
async def get_current_user(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401)
    token = auth[7:]
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.line.me/v2/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid token")
    return r.json()["userId"]

# POST /api/auth/line_callback
async def line_callback(request: Request):
    body = await request.json()
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.line.me/oauth2/v2.1/token",
            data={
                "grant_type":    "authorization_code",
                "code":          body["code"],
                "redirect_uri":  body["redirect_uri"],
                "client_id":     os.environ["LINE_LOGIN_CHANNEL_ID"],
                "client_secret": os.environ["LINE_LOGIN_CHANNEL_SECRET"],
            },
        )
    if r.status_code != 200:
        raise HTTPException(status_code=400)
    token_data   = r.json()
    access_token = token_data["access_token"]
    async with httpx.AsyncClient() as client:
        pr = await client.get(
            "https://api.line.me/v2/profile",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    return JSONResponse({"token": access_token, "user_id": pr.json()["userId"]})

# ── 增量同步：只拉新週報 ──────────────────────────────────
# GET /api/sync/weekly?since=2025-W03
async def sync_weekly(request: Request, user_id: str = Depends(get_current_user)):
    """
    前端帶 since=<last_week_id>，只回傳比這個新的週報
    若沒帶 since，回傳所有待領週報
    """
    since     = request.query_params.get("since")
    week_ids  = await list_pending_weekly(user_id)

    # 過濾：只要比 since 新的
    if since:
        week_ids = [w for w in week_ids if w > since]

    reports = []
    for wid in week_ids:
        report = await pop_weekly_report(user_id, wid)
        if report:
            reports.append(report)
            await set_last_sync(user_id, wid)

    return JSONResponse({
        "reports":   reports,
        "count":     len(reports),
        "has_more":  False,  # 保留給分頁擴充
    })

# GET /api/sync/conversations（對話緩衝，即時補底）
async def sync_conversations(user_id: str = Depends(get_current_user)):
    messages = await pop_buffered_messages(user_id)
    return JSONResponse({"messages": messages})

# ── 路由註冊 ──────────────────────────────────────────────
# app.add_api_route("/api/auth/line_callback",  line_callback,      methods=["POST"])
# app.add_api_route("/api/sync/weekly",         sync_weekly,        methods=["GET"])
# app.add_api_route("/api/sync/conversations",  sync_conversations, methods=["GET"])
