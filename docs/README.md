# MindBot v2 — 技術文件

## 專案概述
LINE Bot 心理自我提問助手，搭配前端日記網站。

---

## 資料夾結構

```
mindbot_v2/
├── main.py                      # FastAPI 主程式、LINE Webhook、API 路由
├── Procfile                     # Railway 部署
├── requirements.txt
├── .env.example                 # 環境變數範本
├── handlers/
│   ├── __init__.py
│   └── message.py               # 完整對話管線（P0→P1→方法→攔截→回覆）
├── services/
│   ├── __init__.py
│   ├── fast_path.py             # P0 靜態評估（微秒，不走 AI）
│   ├── interceptor.py           # P0 Pydantic 攔截器
│   ├── circuit_breaker.py       # P2 斷路器
│   ├── clinical_diagnosis.py    # P1 臨床診斷（Arousal/防衛/破裂）
│   ├── ai_label.py              # 三維情緒標籤
│   ├── crisis.py                # 雙層危機偵測
│   ├── rapport.py               # 關係建立（前兩輪）
│   ├── byron_katie.py           # 四問法
│   ├── sqt.py                   # SQT 自我提問
│   ├── metacognition.py         # 後設認知
│   ├── socratic.py              # 蘇格拉底對話
│   ├── db_persistent.py         # MariaDB CRUD
│   ├── redis_client.py          # Redis 讀寫（含 Lua 原子 pop）
│   └── weekly_scheduler.py      # 週報排程 + AI 摘要
└── static/
    └── prototype.html           # 前端完整單頁應用
```

---

## 對話管線流程

```
用戶訊息
  → Fast-Path（字數/阻斷詞/危機關鍵字）
  → 危機偵測（關鍵字 + AI 雙層）
  → 關係建立（前兩輪）
  → 臨床診斷（Arousal 1-5 / 防衛機制 / 同盟破裂）
  → 情緒標籤（emotion / cognition / need）
  → 方法選擇（Byron Katie / SQT / 後設認知 / 蘇格拉底）
  → P0 攔截器（說教過濾 / 多問句截斷 / 字數限制）
  → 轉介阻尼器
  → 回覆 + 寫入 DB + Redis 緩衝
```

---

## 資料流

```
LINE Bot 對話
  → MariaDB session_messages（持久）
  → Redis conv:{user_id}（7天 TTL 緩衝）

每週一凌晨 3:00（APScheduler）
  → 取上週 MariaDB 資料
  → AI 生成摘要 + 統計
  → 存 MariaDB archives + Redis weekly:{user_id}:{week_id}
  → 刪除原始 session_messages

用戶開啟網站
  → LINE Login OAuth
  → GET /api/sync/weekly?since={last_week_id}（增量）
  → GET /api/sync/conversations
  → 寫入 IndexedDB
  → 本地運算圖表
```

---

## 環境變數

| 變數 | 說明 |
|------|------|
| `LINE_CHANNEL_SECRET` | LINE Bot Webhook 驗簽 |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot 發訊息 |
| `LINE_LOGIN_CHANNEL_ID` | LINE Login OAuth |
| `LINE_LOGIN_CHANNEL_SECRET` | LINE Login OAuth |
| `ANTHROPIC_API_KEY` | Claude API |
| `DB_HOST/PORT/USER/PASSWORD/NAME` | MariaDB |
| `REDIS_URL` | Redis（含密碼） |

---

## Railway 部署步驟

1. 確認所有環境變數已填入
2. 確認 MariaDB / Redis 服務已啟動
3. git push → Railway 自動部署
4. `prototype.html` 第 3 行替換 `LINE_LOGIN_CHANNEL_ID`
5. LINE Bot Webhook URL 設為 `https://{domain}/webhook`

---

## Railway Cron（週排程備用）

若 APScheduler 不穩定，改用 Railway Cron Job：
```
0 19 * * 0   python -m services.weekly_scheduler
```
（UTC 週日 19:00 = 台灣週一凌晨 3:00）

---

## 資料保留政策

| 用戶類型 | 保留期 |
|----------|--------|
| 一般用戶 | 7 天（未登入網站後自動刪除） |
| 危機豁免（crisis_flagged=1） | 30 天 |

---

## 待開發項目

- [ ] `handlers/postback.py`（Flex Message 簽到互動）
- [ ] 每日簽到推播排程
- [ ] 前端 PWA（manifest + Service Worker）
- [ ] `generate_mini_summary`（冷啟動微型摘要）
- [ ] 自動刪除 Cron SQL 腳本
- [ ] 高風險用戶 30 天關懷推播
