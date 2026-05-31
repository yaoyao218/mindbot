# 心事日記 MindBot — 系統技術規格書

> **版本：** v1.0（P0–P2 Pipeline 完成版）  
> **最後更新：** 2026-05-31  
> **部署網址：** https://web-production-dd506.up.railway.app  
> **GitHub：** https://github.com/yaoyao218/mindbot（Private）

---

## 1. 專案概述

心事日記是一套基於 LINE Bot 的心理自我提問助手，結合四種循證心理治療方法（Byron Katie 四問法、SQT 自我提問療法、後設認知療法、蘇格拉底式對話），針對非臨床族群的日常情緒困擾提供結構化引導。

系統特色在於引入三層工程防護（P0–P2），確保 AI 回覆在心理安全邊界內運作，避免不當介入或說教，並在危機情境下強制轉介。

### 技術棧

| 項目 | 選擇 |
|------|------|
| 語言 | Python 3.12 |
| 框架 | FastAPI 0.111 |
| AI 模型 | Claude Sonnet 4.6（Anthropic API） |
| 即時通訊 | LINE Messaging API v3 |
| 資料庫 | MariaDB（生產）/ 記憶體（MVP fallback） |
| 部署 | Railway（Web Service + MySQL Plugin） |

---

## 2. 目錄結構

```
mindbot_v2/
├── main.py                    # FastAPI 入口、Webhook 接收、DB startup
├── requirements.txt
├── Procfile                   # Railway 啟動指令
├── .env.example               # 環境變數範本
├── handlers/
│   ├── message.py             # 完整 P0→P2 訊息處理 pipeline
│   └── postback.py            # 簽到兩段式流程（Flex Message）
└── services/
    ├── fast_path.py           # [P0] 靜態快篩（微秒級）
    ├── interceptor.py         # [P0] Pydantic 回覆攔截器
    ├── clinical_diagnosis.py  # [P1] 臨床診斷（Arousal + 防衛 + 同盟）
    ├── db_persistent.py       # [P2] MariaDB 持久化
    ├── circuit_breaker.py     # [P2] 三態斷路器
    ├── byron_katie.py         # 四問法對話模組
    ├── sqt.py                 # SQT 對話模組
    ├── metacognition.py       # 後設認知對話模組
    ├── socratic.py            # 蘇格拉底對話模組
    ├── crisis.py              # 危機偵測（雙層）
    ├── rapport.py             # 前兩輪關係建立
    ├── ai_label.py            # 情緒標籤分析（Claude API）
    └── session.py             # 記憶體 Session（MVP / fallback）
```

---

## 3. 訊息處理 Pipeline

每次用戶傳訊息，`handlers/message.py` 依序執行以下九個步驟：

```
用戶訊息
  │
  ▼ Step 1  Fast-Path 靜態評估（不走 AI）
  │         • 輸入 ≥ 150 字 → 高波動，Bot 回覆限制為輸入的 40%
  │         • ≤ 5 字 + 阻斷詞 → 情感阻滯，Bot 回覆 ≤ 80 字
  │         • 危機關鍵字 → 直接觸發危機模式
  │
  ▼ Step 2  危機偵測（關鍵字 + AI 雙層確認）
  │         命中 → 附上安心專線 1925，終止對話流程
  │
  ▼ Step 3  關係建立（前兩輪）
  │         第 1 輪：純傾聽，不分析不提問
  │         第 2 輪：傾聽 + 輕詢今天想要什麼
  │         第 3 輪起：進入方法介入
  │
  ▼ Step 4  臨床診斷（AI）
  │         • Arousal Level 1–5（容納之窗評估）
  │         • 防衛機制：理智化 / 外在投射 / 無
  │         • 治療同盟破裂：對抗型 / 退縮型 / 無
  │         破裂 → 停止推進，執行修復語句
  │
  ▼ Step 5  方法安全過濾
  │         Arousal 5 → 禁所有方法，只給危機支持
  │         外在投射 → 禁 Byron Katie
  │         理智化   → 禁後設認知
  │
  ▼ Step 6  四種對話方法（擇一執行）
  │         依 emotion/cognition 標籤選擇
  │
  ▼ Step 7  Pydantic 攔截器
  │         • 說教語句替換（建議你／你應該／你可以嘗試）
  │         • 多問句截斷（只保留第一個問句）
  │
  ▼ Step 8  字數截斷（依 Fast-Path 結果）
  │
  ▼ Step 9  轉介阻尼器
            Arousal 5 → 強制附上 1925
            Arousal 4 → 強烈建議諮商
            Arousal 1–3 → 每日最多 3 次去標籤化推廣
```

---

## 4. 四種對話方法

### 4.1 Byron Katie 四問法
**適用條件：** `cognition = FIXED_BELIEF` 或 `CATASTROPHIZING`

| Phase | 內容 |
|-------|------|
| Phase 0 | 認知融合評估（CFQ-7）；高融合 → 先做前置解融三步 |
| Phase 1 | 解融：把念頭加上「我現在有一個念頭，它說：___」 |
| Phase 2 | 四問本體（Q1 真嗎？Q2 能確定？Q3 你的反應？Q4 沒有它你是誰？）+ 翻轉 |

**論文依據：** CFQ-7（Gillanders et al., 2014）、ACT Defusion（Hayes et al., 2006）

### 4.2 SQT 自我提問療法
**適用條件：** `emotion = ACUTE_DISTRESS` 或 `RUMINATION`

| Step | 內容 |
|------|------|
| 0 | 邀請說出念頭（純傾聽） |
| 1 | 語言解融 |
| 2 | 語言 + 身體雙軌覺察（念頭可信度 + 身體位置） |
| 3 | 手掌比喻：觀察而不追隨 |
| 4 | D-FUSE 念頭可信度再評估 |

**論文依據：** Hayes et al.（2006）、Henriques et al.（2020）D-FUSE、Price & Weng（2021）

### 4.3 後設認知療法（MCT）
**適用條件：** `cognition = LOGICAL_READY`

| Phase | 內容 |
|-------|------|
| Phase 0 | 正向後設認知信念評估（是否相信「一直想有益」）|
| Phase 1 | 有正向信念 → 設計反芻行為實驗（比較想 vs 不想的結果）|
| Phase 2 | MCT 四步：計畫 → 執行 → 監控（分離式正念）→ 評估 |

**論文依據：** Wells（2009）S-REF 模型、Hagen & Kennair（2024）、Strand et al.（2024）

### 4.4 蘇格拉底式對話
**適用條件：** `cognition = INSIGHT_EMERGING`

六策略動態選擇器（非線性，依洞察就緒度 LOW/MEDIUM/HIGH 調整深度）：

| 策略 | 說明 |
|------|------|
| concretize | 拉到具體事件 |
| counter_example | 帶入例外情境 |
| perspective_shift | 換位思考 |
| pattern_recognition | 看見重複模式 |
| standard_check | 對自己 vs 對別人的標準差異 |
| open_discovery | 讓用戶自己說出結論 |

**論文依據：** Padesky（1993）四要素、Vittorio et al.（2022）、Arxiv SIF（2026）

---

## 5. 情緒標籤系統

AI（`ai_label.py`）對每則訊息輸出三維標籤：

| 維度 | 可選值 |
|------|--------|
| emotion | ACUTE_DISTRESS / RUMINATION / SELF_BLAME / CONFUSION / CALM_REFLECTIVE |
| cognition | FIXED_BELIEF / CATASTROPHIZING / LOGICAL_READY / INSIGHT_EMERGING |
| need | NEED_RELEASE / NEED_STRUCTURE / NEED_CHALLENGE / NEED_DISCOVERY |

**方法自動選擇：**
```
ACUTE_DISTRESS 或 RUMINATION    → SQT
FIXED_BELIEF 或 CATASTROPHIZING → Byron Katie
LOGICAL_READY                   → 後設認知
INSIGHT_EMERGING                → 蘇格拉底
```

**中途切換：**
```
任何方法中情緒突然升高（→ ACUTE_DISTRESS）→ 切回 SQT
SQT 走三步 + 情緒穩定                     → 升級原方法
Byron Katie 第二問後 + 洞察萌發           → 升級蘇格拉底
```

---

## 6. P0–P2 工程防護層

### P0：Fast-Path + Pydantic 攔截器

**`fast_path.py`** — 不呼叫 AI，微秒級完成：
- 字數比偵測（≥ 150 字 → 高波動）
- 情感阻斷詞（≤ 5 字 + 不知道／算了 等 → 阻滯）
- 危機關鍵字快篩
- 動態 Bot 輸出上限（高波動：≤ 輸入 40%；阻滯：≤ 80 字）

**`interceptor.py`** — Pydantic 模型驗證回覆品質：
- 黑名單語句過濾（建議你、你應該、你可以嘗試 等）
- 多問句截斷（超過一個問號 → 只保留第一問）

### P1：臨床診斷器（`clinical_diagnosis.py`）

每輪對話呼叫 Claude API 評估：

| 指標 | 說明 |
|------|------|
| Arousal Level 1–5 | 容納之窗；5 = 全面崩潰，強制轉介 |
| 防衛機制 | INTELLECTUALIZATION / EXTERNALIZATION / NONE |
| 同盟破裂 | CONFRONTATION / WITHDRAWAL / NONE |

### P2：持久化 + 斷路器

**`db_persistent.py`** — MariaDB 五張表：

| 資料表 | 內容 |
|--------|------|
| sessions | 對話狀態（method / step / core_belief） |
| session_messages | 每輪訊息紀錄（含角色、字數） |
| session_psych | 每輪心理診斷快照（emotion curve 追蹤） |
| checkins | 每日簽到紀錄 |
| referral_log | 轉介提示次數（阻尼器依據） |

**`circuit_breaker.py`** — 三態狀態機：
- CLOSED（正常）→ 連續 3 次 API 失敗 → OPEN（靜態兜底）→ 60 秒後 HALF_OPEN（探測）

---

## 7. 簽到功能（兩段式流程）

```
用戶輸入「簽到」
  ↓
Stage 1：選情緒（5 個選項 Flex Message）
  ↓
Stage 2：選功能（3 個按鈕 Flex Message）
  ├── 💬 深度對話  → 依情緒決定方法，先收集困擾，進入對話引擎
  ├── ✍️ 寫幾個字  → AI 分析補充文字，給出一句溫暖回應
  └── ✅ 只記錄    → 直接儲存情緒，結束
```

---

## 8. 環境變數

| 變數名稱 | 說明 |
|----------|------|
| `LINE_CHANNEL_SECRET` | LINE Bot Channel Secret |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot Access Token |
| `ANTHROPIC_API_KEY` | Claude API Key |
| `DB_HOST` | MariaDB 主機 |
| `DB_PORT` | 預設 3306 |
| `DB_USER` | 資料庫用戶名稱 |
| `DB_PASSWORD` | 資料庫密碼 |
| `DB_NAME` | 資料庫名稱（建議 `mindbot`）|

> DB 環境變數未設定時，系統自動 fallback 至記憶體 Session，功能完整但重啟後資料消失。

---

## 9. 尚未完成的項目

### 必要（上線前）

| 項目 | 說明 |
|------|------|
| Railway 加入 MySQL Plugin | 填入 DB 環境變數，`init_db()` 才能建表 |
| 整合測試 | 用真實 LINE Bot 跑完整 P0→P2 對話流程 |
| `dialog.py` 與新模組整合確認 | 舊 `dialog.py` 仍存在，需確認新四個對話模組已完全接管 |

### 功能擴充（v2）

| 項目 | 說明 |
|------|------|
| 每日簽到推播 | 每晚 9 點透過 Railway Cron Jobs 推播 Flex Message |
| 前端網站 | LINE Login OAuth + IndexedDB 本地儲存 + 月度報告頁面 |
| 月度歸檔 | 每日凌晨 3 點：30 天前資料 → AI 摘要 + 統計 → 推送至用戶端 |

---

## 10. 本地開發

```bash
# 安裝套件
pip install -r requirements.txt

# 設定環境變數（複製範本）
cp .env.example .env
# 填入 LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, ANTHROPIC_API_KEY

# 啟動伺服器
uvicorn main:app --reload --port 8000

# LINE Webhook 本地測試（需 ngrok）
ngrok http 8000
# 將 https://xxxx.ngrok.io/webhook 貼入 LINE Developers Console
```

---

## 11. 部署（Railway）

```bash
git push origin main   # 自動觸發 Railway 重新部署
```

Railway 會讀取 `Procfile` 執行：
```
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```
