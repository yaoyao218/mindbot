"""
Integration tests for MindBot v2 backend API.

Covers the three core endpoints validated in Sprint 2:
  - GET /api/config
  - GET /app-v2
  - GET /api/sync/conversations

Run:
    cd mindbot_v2
    pytest tests/test_api_v2.py -v
"""

import os
import pytest
from fastapi.testclient import TestClient

# ── App import ──────────────────────────────────────────────
# Import after pytest fixture setup so env-var patches take effect
# before the module-level globals in main.py are evaluated.
from main import app, get_current_user


# ── Fixtures ────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """TestClient that runs startup/shutdown lifecycle once per module."""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def auth_client():
    """
    TestClient with get_current_user dependency overridden.
    Lets us test authenticated endpoints without a real LINE token.
    """
    async def _fake_user():
        return "U_test_user_123"

    app.dependency_overrides[get_current_user] = _fake_user
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


# ══════════════════════════════════════════════════════════════
# 1. GET /api/config
# ══════════════════════════════════════════════════════════════

class TestGetConfig:

    def test_response_shape(self, client):
        """回傳 JSON 必須包含三個規格書要求的鍵。"""
        r = client.get("/api/config")
        assert r.status_code == 200
        body = r.json()
        assert "liff_id"               in body, "缺少 liff_id"
        assert "line_login_channel_id" in body, "缺少 line_login_channel_id"
        assert "app_url"               in body, "缺少 app_url"

    def test_liff_id_reads_env_var(self, monkeypatch):
        """LIFF_ID 環境變數設定後必須正確傳給前端，不能回傳預設值。"""
        monkeypatch.setenv("LIFF_ID", "2001234567-TestLiff")
        # 每次需要新的 TestClient 讓 os.environ 變更生效
        with TestClient(app) as c:
            r = c.get("/api/config")
        assert r.status_code == 200
        assert r.json()["liff_id"] == "2001234567-TestLiff", (
            "liff_id 應等於環境變數 LIFF_ID；若仍是空字串代表 .env 未讀到"
        )

    def test_liff_id_empty_when_env_unset(self, monkeypatch):
        """未設定 LIFF_ID 時應回傳空字串，不應回傳 mock 預設值。"""
        monkeypatch.delenv("LIFF_ID", raising=False)
        with TestClient(app) as c:
            r = c.get("/api/config")
        assert r.status_code == 200
        assert r.json()["liff_id"] == "", (
            "未設定 LIFF_ID 時應為空字串；如果看到 DEFAULT_MOCK_LIFF_ID 代表環境變數硬編碼了"
        )

    def test_app_url_default_is_railway(self, monkeypatch):
        """未設定 APP_URL 時預設應指向 Railway 生產域名。"""
        monkeypatch.delenv("APP_URL", raising=False)
        with TestClient(app) as c:
            r = c.get("/api/config")
        assert "railway.app" in r.json()["app_url"]


# ══════════════════════════════════════════════════════════════
# 2. GET /app-v2
# ══════════════════════════════════════════════════════════════

class TestServeAppV2:

    def test_returns_200(self, client):
        """路由必須存在且回傳 200，不得 404 或 500。"""
        r = client.get("/app-v2")
        assert r.status_code == 200, (
            f"GET /app-v2 回傳 {r.status_code}；"
            "請確認 static/public/index.html 存在且 main.py 掛載路徑正確"
        )

    def test_content_type_is_html(self, client):
        """必須是 text/html，不能是 JSON 或純文字。"""
        r = client.get("/app-v2")
        assert "text/html" in r.headers.get("content-type", ""), (
            "Content-Type 應為 text/html；FileResponse 路徑可能指向錯誤檔案"
        )

    def test_contains_app_entrypoint(self, client):
        """HTML 必須包含 app.js 的 <script> 掛載點，確認模組化 SPA 骨架正確。"""
        r = client.get("/app-v2")
        html = r.text
        assert 'src="../src/app.js"' in html or 'src="' in html, (
            "index.html 找不到 app.js script 標籤；靜態目錄結構可能有誤"
        )
        assert "app-runtime" in html, (
            "index.html 缺少 #app-runtime 容器；SPA 渲染根節點遺失"
        )
        assert "sync-label" in html, (
            "index.html 缺少 #sync-label；三態指示器 HTML 骨架遺失"
        )

    def test_static_directory_mounted(self, client):
        """靜態目錄 /static 必須成功掛載，CSS 能被 200 取得。"""
        # Tailwind CDN 在生產環境前會有 styles.css；先確認目錄本身可達
        r = client.get("/static/public/index.html")
        # 200 = 掛載成功；404 = StaticFiles 路徑錯誤
        assert r.status_code == 200, (
            "GET /static/public/index.html 回傳 404；"
            "main.py 的 app.mount('/static', ...) 目錄設定有誤"
        )


# ══════════════════════════════════════════════════════════════
# 3. GET /api/sync/conversations
# ══════════════════════════════════════════════════════════════

class TestSyncConversations:

    # ── 未授權 ──────────────────────────────────────────────

    def test_no_auth_returns_401(self, client):
        """未帶 Authorization header 應拒絕並回傳 401。"""
        r = client.get("/api/sync/conversations")
        assert r.status_code == 401

    def test_invalid_token_returns_401(self, client):
        """無效 Bearer token 應回傳 401，不得 500。"""
        r = client.get(
            "/api/sync/conversations",
            headers={"Authorization": "Bearer totally_fake_token"},
        )
        assert r.status_code == 401

    def test_missing_bearer_prefix_returns_401(self, client):
        """缺少 'Bearer ' 前綴應回傳 401。"""
        r = client.get(
            "/api/sync/conversations",
            headers={"Authorization": "just_a_token"},
        )
        assert r.status_code == 401

    # ── 授權通過 ─────────────────────────────────────────────

    def test_authenticated_returns_200(self, auth_client):
        """有效 user_id 通過 Depends 後應回傳 200。"""
        r = auth_client.get("/api/sync/conversations")
        assert r.status_code == 200

    def test_response_shape(self, auth_client):
        """
        回傳 JSON 必須是 { messages: list, count: int }。
        messages 內每筆若有資料，需包含 role 與 content。
        """
        r = auth_client.get("/api/sync/conversations")
        body = r.json()
        assert "messages" in body, "缺少 messages 鍵"
        assert "count"    in body, "缺少 count 鍵"
        assert isinstance(body["messages"], list), "messages 必須是陣列"
        assert isinstance(body["count"],    int),  "count 必須是整數"
        assert body["count"] == len(body["messages"]), (
            "count 必須等於 messages 陣列長度（原子一致性）"
        )

    def test_message_fields_when_present(self, auth_client, monkeypatch):
        """
        若 buffer 有資料，每筆訊息必須包含 role 與 content 欄位，
        且 role 只能是 'user' 或 'assistant'。
        """
        fake_msgs = [
            {"timestamp": 1717424600000, "role": "user",
             "content": "我覺得最近壓力有點大..."},
            {"timestamp": 1717424602000, "role": "assistant",
             "content": "溫柔的傾聽中。壓力大時，試著把注意力帶回呼吸..."},
        ]

        # 直接 patch in-process buffer 的 get 方法
        import services.message_buffer as mb
        monkeypatch.setattr(mb, "get", lambda user_id: fake_msgs)

        r = auth_client.get("/api/sync/conversations")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 2

        for msg in body["messages"]:
            assert "role"    in msg, "每筆訊息缺少 role"
            assert "content" in msg, "每筆訊息缺少 content"
            assert msg["role"] in ("user", "assistant"), (
                f"role 值 '{msg['role']}' 不合法，只允許 user / assistant"
            )

    def test_user_id_query_param_accepted(self, client):
        """
        user_id 以 query param 傳入但無 Authorization header 仍應 401，
        確認不走 query-param bypass（安全邊界）。
        """
        r = client.get("/api/sync/conversations?user_id=U_attacker")
        assert r.status_code == 401, (
            "user_id query param 不應繞過 Authorization 驗證"
        )
