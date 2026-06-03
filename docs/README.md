# 心事日記 MindBot v2 — 技術文件

## 專案概述

LINE Bot 心理陪伴系統，整合 LIFF Web App 前端日記。
部署於 Railway，資料庫使用 PostgreSQL + Redis。

---

## 目錄結構

```
mindbot_v2/
├── main.py                        # FastAPI 主程式、Webhook、所有 API 路由
├── Procfile                       # Railway 部署指令
├── requirements.txt
├── .env.example                   # 環境變數範本（不含實際金鑰）
├── .python-version                # Python 3.12

├── handlers/
│   ├── message.py                 # 主對話管線（危機→診斷→Companion→象徵→Nudge）
│   ├── onboarding.py              # Follow 事件歡迎引導
│   └── postback.py                # Flex Message 按鈕互動（簽到、塔羅翻牌）

├── services/
│   ├── llm.py                     # Claude API 封裝（Sonnet / Haiku 分層）
│   ├── fast_path.py               # P0 靜態評估（微秒，不走 AI）
│   ├── interceptor.py             # 回覆過濾（禁用語、說教偵測）
│   ├── crisis.py                  # 雙層危機偵測（關鍵字 + AI）
│   ├── companion.py               # 主對話 4步接話 + Rupture Repair
│   ├── clinical_diagnosis.py      # P1 臨床診斷（Arousal / 防衛機制 / 同盟破裂）
│   ├── ai_label.py                # 三維情緒標籤（emotion / cognition / need）
│   ├── symbolic.py                # 象徵系統（塔羅 78 張 + 名言佳句）
│   ├── tarot_projective.py        # 投射塔羅模組（覆蓋牌 / 揭示牌 / 收尾字卡）
│   ├── tarot_quotes_pool.py       # 投射牌庫（8 張）+ 哲人名言庫（11 情緒分類）
│   ├── nudge.py                   # Streak / 成長樹 / 週任務 / 情緒詞典 / 里程碑
│   ├── daily_question.py          # 每日一問推播排程
│   ├── daily_narrative.py         # 每日敘事摘要
│   ├── weekly_scheduler.py        # 週報生成（arousal_curve / emotion_counts）
│   ├── line_weekly_push.py        # 週報 LINE 推播
│   ├── db_persistent.py           # PostgreSQL CRUD（session / archive / calendar）
│   ├── redis_client.py            # Redis（對話緩衝 / 週報快取 / 分散式鎖）
│   ├── session.py                 # 記憶體 Session fallback
│   ├── message_buffer.py          # 訊息緩衝區（in-process）
│   ├── login_token.py             # 一次性登入 token
│   ├── archive_scheduler.py       # 月度歸檔排程
│   └── __init__.py

├── static/
│   ├── public/
│   │   └── index.html             # LIFF SPA 入口（唯一前端 HTML）
│   └── src/
│       ├── app.js                 # AppController（路由 / 初始化 / 同步）
│       ├── db.js                  # Dexie.js IndexedDB 封裝
│       └── components/
│           ├── Dashboard.js       # 週報折線圖 + 情緒分佈 + 名言卡
│           ├── TarotBlind.js      # 塔羅翻牌元件（防誤觸）
│           ├── CalendarView.js    # 情緒月曆
│           ├── Timeline.js        # 對話時間軸
│           └── Settings.js        # 設定頁（匯出 / 本地備份 / 登出）

├── tests/
│   └── test_api_v2.py             # API 端點測試
└── docs/
    └── README.md                  # 本文件
```

---

## 對話管線流程

```
LINE 用戶訊息
  ↓
雙層分散式鎖（Redis NX + asyncio 記憶體備援）
  ↓
關鍵字路由（簽到 / 說明 / 登入 / 推播設定…）
  ↓
Fast-Path 靜態評估（STAGNANT / 危機關鍵字）
  ↓
危機偵測 → 1925 安心專線罐頭（Layer 1）
  ↓
P1 臨床診斷（Arousal 1-5 / 防衛機制 / 同盟破裂）
  ├─ alliance_rupture → Rupture Repair（口語化道歉，冷卻 2 輪）
  └─ 正常 → Companion 4步接話
  ↓
STAGNANT → 投射塔羅 Flex（覆蓋牌→翻牌→AI 投射問句）
  ↓
收尾語偵測 → 封存字卡 Flex（洞察 + 名言 + 塔羅 + 查看按鈕）
  ↓
Nudge Pipeline（Streak / 成長樹 / 詞典解鎖 / 里程碑）
  ↓
攔截器（禁用語過濾）→ LINE 回覆
  ↓
PostgreSQL 寫入 + Redis 緩衝
```

---

## 前端架構

| 入口 | URL | 說明 |
|------|-----|------|
| LIFF SPA | `https://liff.line.me/2010279401-zI4pqH8D` | 主要入口（LINE 內開啟）|
| 直連 | `https://web-production-dd506.up.railway.app/app-v2` | 瀏覽器直連 |
| 登入跳轉 | `/auto-login?t=TOKEN` → `/app-v2#dashboard` | Bot 發送一次性連結 |
| 月曆入口 | `/calendar` → `/app-v2#calendar` | LINE 訊息連結 |
| 週報入口 | `/report` → `/app-v2#weeks` | LINE 訊息連結 |

Hash 路由：`#dashboard` / `#calendar` / `#timeline` / `#settings`

---

## 環境變數

| 變數 | 說明 |
|------|------|
| `LINE_CHANNEL_SECRET` | LINE Bot Webhook 驗簽 |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot 發訊息 |
| `LIFF_ID` | LIFF App ID（2010279401-zI4pqH8D）|
| `ANTHROPIC_API_KEY` | Claude API |
| `DATABASE_URL` | PostgreSQL 連線字串 |
| `REDIS_URL` | Redis 連線字串 |
| `APP_URL` | 部署域名（選填，預設 LIFF URL）|

---

## 部署（Railway）

```bash
git push origin main   # 自動觸發 Railway CI/CD
```

啟動指令（Procfile）：
```
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

週排程（APScheduler 內建，Railway 無需額外 Cron）：
- 每週一 03:00 台灣時間 → 週報生成 + LINE 推播
- 每分鐘 → 今日一問推播排程檢查

---

## 象徵系統一覽

| 模組 | 觸發 | 內容 |
|------|------|------|
| 塔羅象徵（78張）| 對話收尾 | 大/小阿爾克那依情緒+強度選牌 |
| 投射塔羅（8張）| STAGNANT 敷衍 | 覆蓋牌→翻牌→AI 投射問句 |
| 哲人名言庫 | 收尾/低喚起 | 11 情緒分類，附作者 |
| 收尾封存字卡 | 收尾語偵測 | 洞察+名言+塔羅 Flex Message |
| 里程碑塔羅 | 第 7/14/30 天 | 成長主題大阿爾克那牌池 |
| 情緒詞典 | 關鍵詞觸發 | 8 個心理學概念即時解鎖 |
| 成長樹 | 每 5 輪+簽到 | 5 階段升階（種子→結果）|
| Streak 火焰 | 每日對話 | 連續天數里程碑訊息 |
