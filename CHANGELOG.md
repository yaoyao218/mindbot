# CHANGELOG — 心事日記 MindBot v2

---

## 2026-06-04 關鍵測試病理分析與即時修復

### 背景
測試案例：用戶表達「期末報告緊張、胃部攪動、吃不下飯、極度焦慮」，Bot 瘋狂重複「嗯——然後呢？」，並在用戶點擊「🛌 睡前安靜聊聊」後依然跳針。本次修復針對五個根本缺陷進行外科手術。

---

### 1. 臨床引導引擎 Socratic 跳針修復
**檔案**：`services/companion.py`

**問題**：`COMPANION_SYSTEM` Prompt 缺乏問句多樣性約束，Bot 將「嗯——然後呢？」當成萬用句陷入迴圈；API 失敗時 fallback 字串直接輸出同一句話加重問題。

**修復**：
- 在 `COMPANION_SYSTEM` 加入「問句多樣性（違反即失敗）」區塊，明確禁止連續兩輪使用相同問句，要求每輪引導問句必須具體扣住本輪新出現的情緒詞或身體感受。
- 將 API 失敗 fallback 從 `"嗯——\n然後呢？"` 改為 `"嗯，你說的這些我都在聽著。"`。

---

### 2. 破裂修復模式過早結束（Rupture Cooldown 保護期）
**檔案**：`services/companion.py`

**問題**：`get_reply()` 只檢查 `is_rupture` 旗標，修復觸發一輪後旗標清零，下一輪直接回到普通模式。臨床上，破裂後脆弱期應維持 2–3 輪。

**修復**：
- 新增 `RUPTURE_COOLDOWN_SYSTEM` / `RUPTURE_COOLDOWN_PROMPT`：修復後保護期專用系統提示，禁止任何問號，要求純粹在場聆聽（重複用戶最有重量的詞），不再重複道歉。
- `get_reply()` 在 `is_rupture` 判斷之後追加 `cooldown > 0` 分支，進入保護期模式；cooldown 遞減仍由 `message.py` 診斷區塊負責，避免雙重遞減。

```python
# companion.py — 修復後的狀態機
if is_rupture:          # 首輪：正式道歉 + 設 cooldown=2
    ...
    return reply, {"psych": {..., "rupture_repair_cooldown": 2}}

if cooldown > 0:        # 保護期（2→1→0）：在場聆聽，不再道歉
    ...
    return reply, {}
```

---

### 3. 系統功能跳轉未清空脈絡（Session 污染與語詞去時間化）
**檔案**：`handlers/message.py`、`handlers/postback.py`、`services/daily_question.py`

**問題一（Session 污染）**：用戶點擊情境選單後，Bot 仍帶著舊 `history`、`alliance_rupture`、`rupture_repair_cooldown` 進入新對話，導致跳針迴圈污染全新起點。

**問題二（語詞時間綁定）**：舊版「🛌 睡前安靜聊聊」在語義上限制了用戶的使用情境，與 24 小時隨身陪伴的產品定位相悖。

**修復**：
- 將所有入口統一更名為 **「🪐 靜心深度傾聽」**（去時間化，任何時間點擊都不產生違和感）。
- 在 `message.py` 選單跳轉處（所有路由之前）加入物理重置邏輯：

```python
if text == "🪐 靜心深度傾聽":
    session["history"] = []
    session["psych"] = {
        "current_context": "deep",
        "alliance_rupture": None,
        "rupture_repair_cooldown": 0,
        "defense_mechanism": None,
        "method": "Initial",
    }
    await save_session(user_id, session)
    await _reply(reply_token,
        "想給自己一段安靜的時間，好好傾聽內心。\n\n現在，你調整到舒服的姿勢了嗎？感覺如何？",
        line_bot_api)
    return
```

- `postback.py` 的 `handle_set_context()` deep 分支歡迎語同步更新為一致的去時間化文案。
- `daily_question.py` 推播卡片按鈕 label 同步更新。

**新歡迎語**（提案 1 · 心靈流派）：
> 想給自己一段安靜的時間，好好傾聽內心。
> 現在，你調整到舒服的姿勢了嗎？感覺如何？

---

### 4. 核心診斷大腦確認已接入主流程
**檔案**：`handlers/message.py`（第 330–354 行）

**確認狀態**：`clinical_diagnosis.diagnose()` 已在前次修復中正確接入，位於 `companion.get_reply()` 之前執行，並帶有 `rupture_repair_cooldown` 冷卻保護邏輯。本次測試後確認無需再修。

---

---

### 5. 敷衍用字全域禁令與情感反映強制準則（Prompt Engineering Patch）
**檔案**：`services/companion.py`

**病因**：在 2026-06-04 壓力測試中，AI 面對急性焦慮的用戶連續輸出「嗯——然後呢？」與罐頭式同理句（「撐了那麼久才說出來」），導致治療同盟當場破裂。問題根源在於 Prompt 沒有明確的文字層面護欄。

**修復**：新增共享常數 `_STYLE_RULES`，串接於 `COMPANION_SYSTEM`、`RUPTURE_REPAIR_SYSTEM`、`SOCRATIC_SYSTEM` 三個 System Prompt 末端。

禁令涵蓋三層：
1. **敷衍套用字眼**：明列「嗯——然後呢？」「喔喔」「了解」「好吧」「原來如此」及罐頭同理句等不得出現的具體字串
2. **情感反映強制準則**：引導時必須重複用戶的身體感官詞彙或情感詞彙（Reflective Listening），禁止空洞反問
3. **反高姿態心理學套版**：禁止「你很有勇氣」「光是開口就很不容易」等表揚性罐頭句，要求人味取代協議執行感

同步移除 `COMPANION_SYSTEM` Rapport 區塊中的罐頭範例文字（「撐了那麼久才說出來，光是開口就已經很不容易了」），改為純語氣指引，防止模型直接複製。

---

### 6. 蘇格拉底問法動態降級與高喚起安全護盾
**檔案**：`services/companion.py`

**病因**：測試中用戶處於 arousal 4（胃部攪動、急性焦慮）狀態，系統卻啟動含問句的陪伴模式，導致防禦加劇。`COMPANION_SYSTEM` 的「溫和引導」問句在高喚起場景下仍具壓迫性。

**修復**：在 Gentle Confrontation 之後、default companion 之前插入雙層防護閘：

**層一 — Socratic 嚴格門檻**（三條件同時成立才允許精準反問）：
```python
if current_method == "Socratic":
    is_rational_long_text = (
        len(user_text) > 50
        and defense == "INTELLECTUALIZATION"
        and arousal_level <= 3
    )
    if not is_rational_long_text:
        current_method = "Supportive_Reflection"  # 降級
```

**層二 — 高喚起安全護盾**（`arousal >= 4` 時無條件降級）：
```python
elif arousal_level >= 4:
    current_method = "Supportive_Reflection"
```

**新增兩個 Prompt**：
- `SUPPORTIVE_REFLECTION_SYSTEM`：零問句、純情感反映技術，把用戶痛苦原話映射回給他，上限 40 字。
- `SOCRATIC_SYSTEM`：精準反問，一句承認 + 一句指向內心假設的問句，上限 55 字，需三條件全過才啟動。

**臨床意義**：原本 `arousal >= 4` 的焦慮場景（如期末壓力、胃痛、心悸）將自動進入純情感反映模式，完全消除問句壓力；Socratic 問法退化為僅在用戶主動長篇理性分析時才出現的精準工具。

---

---

### 7. Supportive_Reflection 提問頻率隔離鎖
**檔案**：`services/companion.py`

**修復**：在 `Supportive_Reflection` 分支加入逐輪提問頻率檢查。往前掃描最後一條 bot 回覆，若含 `？` 或 `?` 則本輪強制零問號（靜默陪伴）；否則允許一個極度溫和的當下感官邀請。規則以 `allow_question_directive` 字串動態注入 prompt，AI 無法繞過。

---

### 8. 求救訊號臨床三階層處方箋分流
**檔案**：`services/companion.py`

**背景**：解決 AI 面對「我該怎麼辦」時流於說教或過度反映的兩極化失敗體驗。

**實作**：在 `Supportive_Reflection` 分支頂端加入求救關鍵字偵測（`該怎麼辦`、`怎麼辦`、`怎麼做`、`救我` 等 9 組），命中後依 `arousal_level` 分三層路由：

| 層級 | 條件 | 模式 | 核心策略 |
|------|------|------|---------|
| Level 1 | arousal == 5 | `GROUNDING_SYSTEM` | 零提問，帶領身體著陸（觸摸質地 / 4-4-4 呼吸 / 五感掃描），最多 120 字 |
| Level 2 | arousal == 4 | `MICRO_FOCUS_SYSTEM` | 禁解大題，微粒化為「當下五分鐘一件微小行動」，最多 100 字 |
| Level 3 | arousal ≤ 3 | `ACT_VALUE_PROBE_SYSTEM` | ACT 核心價值探針，一個溫和開放問句引導釐清自身在乎的事，最多 80 字 |

三層路由命中後直接 `return`，不進入常規 Supportive_Reflection 流程，避免邏輯混用。

---

---

### 9. 精準對話收尾：雙軌封存機制（主動邀請 + 多維度被動攔截）
**檔案**：`handlers/message.py`、`services/companion.py`、`services/nudge.py`

**背景**：原收尾偵測過於模糊，第 1、2 輪就塞入封存字卡，或用戶說「晚安」時 AI 仍回應一句再封存。

#### Track A — 第 5 輪主動封存邀請
- `companion.py`：`total_turn >= 5 AND current_context == "deep"` 時注入 `closure_patch`，AI 在情感反映後自然提議封存，並標記 `closure_invite_shown = True` 防止重複
- `message.py`：偵測到 `closure_invite_shown` 後，在 TextMessage 附加 QuickReply：「🌙 封存今天（text: 好，先這樣 🌙）」+ 「繼續說說」，一鍵確認或繼續
- 點擊「好，先這樣 🌙」→ 觸發既有 `detect_closing_signal()` → `_is_closing = True` → SummaryModule

#### Track B-1 — 被動關鍵字早攔截
- 新增 `_PASSIVE_CLOSING_KEYWORDS`（18 組：先這樣、晚安、謝謝你、拜拜、感恩、明天見…）
- 在 dialog 中偵測到關鍵字 → **跳過 AI 對話**，直接運行 SummaryModule（insight + tarot + quote + closure flex），完整閉環後 return

#### Track B-2 — Stagnant 敷衍阻斷
- 連續 2 輪用戶輸入 ≤3 字 → 在正常 AI 回覆後附加「🌙 封存今天」QuickReply 按鈕，溫柔詢問是否封存（不自動關閉）

#### `nudge.py` 更新
- `should_show_closing()`：`current_context == "deep"` 時停用 `total_turn % 5` 輪數觸發，僅保留 Arousal 驟降條件，防止與 Track A 雙重觸發

---

## 變更影響範圍

| 檔案 | 變更類型 |
|------|---------|
| `services/companion.py` | Bug Fix × 3（跳針防護、cooldown 保護期、fallback 文案）+ Feature（Socratic 降級 + 高喚起護盾 + 兩個新 Prompt + 全域文風禁令 `_STYLE_RULES`） |
| `handlers/message.py` | Bug Fix（Session 污染）+ Feature（語詞去時間化） |
| `handlers/postback.py` | Feature（歡迎語去時間化） |
| `services/daily_question.py` | Feature（按鈕語詞更新） |
