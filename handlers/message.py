"""
handlers/message.py — 整合版 P0-P2 Pipeline
流程：Fast-Path → 危機偵測 → 關係建立 → P1 臨床診斷 → 方法過濾 → 對話方法 → 攔截器 → 轉介 → 回覆
"""

import random
from linebot.v3.messaging import (
    MessagingApi, ReplyMessageRequest,
    TextMessage, FlexMessage, FlexContainer
)
from linebot.v3.webhooks import MessageEvent

# P0
from services.fast_path import evaluate as fast_evaluate, FastPathResult
from services.interceptor import process_response
from services.circuit_breaker import get_breaker

# P1
from services.clinical_diagnosis import diagnose, get_rupture_repair_response, DiagnosisResult

# 對話方法
from services.rapport import rapport_turn_1, rapport_turn_2
from services.crisis import detect_crisis, get_crisis_response
from services.byron_katie import get_reply as bk_reply
from services.sqt import get_reply as sqt_reply
from services.metacognition import get_reply as mct_reply
from services.socratic import get_reply as socratic_reply
from services.ai_label import analyze_message

# DB（優先用持久化版，ImportError 或 DB 連線失敗都 fallback 到記憶體版）
from services.session import (
    get_session as _mem_get_session,
    save_session as _mem_save_session,
    clear_session as _mem_clear_session,
)

async def _noop(*a, **kw): pass
async def _zero(*a, **kw): return 0

try:
    import services.db_persistent as _dbp

    async def get_session(user_id):
        try:
            return await _dbp.get_session(user_id)
        except Exception:
            return await _mem_get_session(user_id)

    async def save_session(user_id, session):
        try:
            await _dbp.save_session(user_id, session)
        except Exception:
            await _mem_save_session(user_id, session)

    async def clear_session(user_id):
        try:
            await _dbp.clear_session(user_id)
        except Exception:
            await _mem_clear_session(user_id)

    async def append_message(user_id, role, text):
        try:
            await _dbp.append_message(user_id, role, text)
        except Exception:
            pass

    async def save_psych_state(user_id, psych, turn):
        try:
            await _dbp.save_psych_state(user_id, psych, turn)
        except Exception:
            pass

    async def count_today_referrals(user_id, rtype="routine"):
        try:
            return await _dbp.count_today_referrals(user_id, rtype)
        except Exception:
            return 0

    async def log_referral(user_id, rtype):
        try:
            await _dbp.log_referral(user_id, rtype)
        except Exception:
            pass

    async def save_checkin(user_id, data):
        try:
            await _dbp.save_checkin(user_id, data)
        except Exception:
            pass

    DB_MODE = "persistent_with_fallback"

except ImportError:
    get_session = _mem_get_session
    save_session = _mem_save_session
    clear_session = _mem_clear_session
    append_message = _noop
    save_psych_state = _noop
    count_today_referrals = _zero
    log_referral = _noop
    save_checkin = _noop
    DB_MODE = "memory"

CHECKIN_KEYWORDS = ["簽到", "check in", "checkin", "今天狀態"]
START_KEYWORDS = ["開始", "start", "你好", "hi", "hello", "嗨", "哈囉"]
HELP_KEYWORDS = ["說明", "help", "怎麼用", "功能"]
STOP_KEYWORDS = ["停止", "結束對話", "不想說了", "先這樣"]

METHOD_MAP = {
    "BYRON_KATIE": bk_reply,
    "SQT": sqt_reply,
    "METACOGNITION": mct_reply,
    "SOCRATIC": socratic_reply,
}

# 每次對話最多連續 2 輪關係建立（rapport）
RAPPORT_MAX_TURNS = 2


async def handle_message(event: MessageEvent, line_bot_api: MessagingApi):
    user_id = event.source.user_id
    text = event.message.text.strip()
    reply_token = event.reply_token

    # ── 關鍵字路由（不走 pipeline）─────────────────────────
    if any(kw in text.lower() for kw in CHECKIN_KEYWORDS):
        await send_checkin_flex(reply_token, line_bot_api)
        return
    if any(kw in text.lower() for kw in START_KEYWORDS):
        await send_welcome(reply_token, line_bot_api)
        return
    if any(kw in text.lower() for kw in HELP_KEYWORDS):
        await send_help(reply_token, line_bot_api)
        return

    # ── 停止對話 ────────────────────────────────────────────
    session_check = await get_session(user_id)
    if any(kw in text for kw in STOP_KEYWORDS) and session_check.get("in_dialog"):
        await clear_session(user_id)
        msg = "好的，我們先在這裡停下來。\n\n隨時想繼續，或有什麼想說的，都可以傳訊息給我。"
        await _reply(reply_token, msg, line_bot_api)
        return

    # ── 取得 Session ────────────────────────────────────────
    session = await get_session(user_id)

    # 進行中的簽到補充
    if session.get("pending_checkin"):
        await handle_checkin_supplement(event, line_bot_api, session, text)
        return

    # ── 步驟一：Fast-Path 靜態評估 ──────────────────────────
    fp_result: FastPathResult = fast_evaluate(text)

    # ── 步驟二：危機偵測（雙層）────────────────────────────
    is_crisis = fp_result.is_crisis or await detect_crisis(text)
    if is_crisis:
        crisis_msg = get_crisis_response()
        await _reply(reply_token, crisis_msg, line_bot_api)
        await append_message(user_id, "bot", crisis_msg)
        # 清除對話 session，危機後重置
        session["in_dialog"] = False
        await save_session(user_id, session)
        return

    # 儲存用戶訊息
    await append_message(user_id, "user", text)
    session.setdefault("history", [])
    session["history"].append({"role": "user", "text": text})

    # ── 步驟三：關係建立（前兩輪）──────────────────────────
    total_turn = session.get("total_turn", 0) + 1
    session["total_turn"] = total_turn

    if total_turn <= RAPPORT_MAX_TURNS and not session.get("in_dialog"):
        if total_turn == 1:
            reply_text = await rapport_turn_1(text)
        else:
            first_msg = session["history"][0]["text"] if session["history"] else text
            reply_text = await rapport_turn_2(text, first_msg)

        reply_text = process_response(reply_text, fp_result)
        session["history"].append({"role": "bot", "text": reply_text})
        await save_session(user_id, session)
        await append_message(user_id, "bot", reply_text)
        await _reply(reply_token, reply_text, line_bot_api)
        return

    # ── 步驟四：P1 臨床診斷 ─────────────────────────────────
    breaker = get_breaker()
    diagnosis: DiagnosisResult

    if breaker.can_attempt():
        try:
            diagnosis = await diagnose(text, session["history"], total_turn)
            breaker.record_success()
        except Exception as e:
            print(f"[Clinical Diagnosis Failed] {e}")
            breaker.record_failure()
            fallback = breaker.get_fallback(3)
            await _reply(reply_token, fallback, line_bot_api)
            return
    else:
        # Circuit breaker OPEN：靜態兜底
        current_arousal = session.get("psych", {}).get("arousal_level", 3)
        fallback = breaker.get_fallback(current_arousal)
        await _reply(reply_token, fallback, line_bot_api)
        return

    # 儲存診斷狀態
    psych_data = {
        "arousal_level": diagnosis.arousal_level,
        "defense_mechanism": diagnosis.defense_mechanism,
        "alliance_rupture": diagnosis.alliance_rupture,
    }
    session["psych"] = psych_data
    await save_psych_state(user_id, psych_data, total_turn)

    # 治療同盟破裂 → 立刻修復，暫停推進
    if diagnosis.should_pause_method and diagnosis.alliance_rupture != "NONE":
        repair_msg = get_rupture_repair_response(diagnosis.alliance_rupture)
        repair_msg = process_response(repair_msg, fp_result)
        session["history"].append({"role": "bot", "text": repair_msg})
        await save_session(user_id, session)
        await append_message(user_id, "bot", repair_msg)
        await _reply(reply_token, repair_msg, line_bot_api)
        return

    # Arousal 5 → 強制危機支持
    if diagnosis.arousal_level == 5:
        crisis_msg = get_crisis_response()
        await _reply(reply_token, crisis_msg, line_bot_api)
        await append_message(user_id, "bot", crisis_msg)
        await log_referral(user_id, "crisis")
        return

    # ── 步驟五：方法安全過濾 + 選擇方法 ────────────────────
    if not session.get("in_dialog"):
        # 第一次進入對話：AI 標籤分析
        labels = await analyze_message(text)
        session["labels"] = labels
        suggested = labels.get("suggested_method", "SQT")

        # 防衛機制過濾
        forbidden = diagnosis.forbidden_methods()
        if suggested in forbidden:
            fallback_method = _fallback_method(suggested, forbidden)
            suggested = fallback_method

        session["in_dialog"] = True
        session["method"] = suggested
        session["phase"] = 0
        session["step"] = 0
        session["core_belief"] = labels.get("core_belief")
        psych_data.update({"emotion": labels.get("emotion"), "cognition": labels.get("cognition"), "method": suggested})
        await save_psych_state(user_id, psych_data, total_turn)
    else:
        # 對話進行中：檢查是否需要切換方法
        current_method = session.get("method", "SQT")
        forbidden = diagnosis.forbidden_methods()
        if current_method in forbidden:
            new_method = _fallback_method(current_method, forbidden)
            if new_method != current_method:
                session["method"] = new_method
                session["phase"] = 0
                session["step"] = 0

    method = session.get("method", "SQT")
    method_fn = METHOD_MAP.get(method, sqt_reply)

    # ── 步驟六：呼叫對話方法 ────────────────────────────────
    if breaker.can_attempt():
        try:
            raw_reply, updates = await method_fn(session, text)
            breaker.record_success()
        except Exception as e:
            print(f"[Method {method} Failed] {e}")
            breaker.record_failure()
            raw_reply = breaker.get_fallback(diagnosis.arousal_level)
            updates = {}
    else:
        raw_reply = breaker.get_fallback(diagnosis.arousal_level)
        updates = {}

    # 更新 session
    for k, v in updates.items():
        session[k] = v

    # ── 步驟七、八：攔截器 + 字數截斷 ──────────────────────
    reply_text = process_response(raw_reply, fp_result)

    # ── 步驟九：轉介阻尼器 ──────────────────────────────────
    referral_suffix = await _get_referral_suffix(user_id, diagnosis)
    if referral_suffix:
        reply_text = reply_text.rstrip() + "\n\n" + referral_suffix

    # 回覆並儲存
    session["history"].append({"role": "bot", "text": reply_text})
    await save_session(user_id, session)
    await append_message(user_id, "bot", reply_text)
    await _reply(reply_token, reply_text, line_bot_api)


def _fallback_method(original: str, forbidden: list[str]) -> str:
    """方法被禁用時的替代方案"""
    priority = ["SQT", "SOCRATIC", "METACOGNITION", "BYRON_KATIE"]
    for m in priority:
        if m not in forbidden:
            return m
    return "SQT"


async def _get_referral_suffix(user_id: str, diagnosis: DiagnosisResult) -> str:
    """轉介阻尼器：決定是否附上轉介訊息"""
    arousal = diagnosis.arousal_level

    if arousal == 5:
        await log_referral(user_id, "crisis")
        return "安心專線 1925，24小時都有人接。"

    if arousal == 4:
        await log_referral(user_id, "strong")
        return "如果可以的話，和專業諮商師談談會很有幫助。"

    # Arousal 1-3：每日最多 3 次日常推廣
    count = await count_today_referrals(user_id, "routine")
    if count < 3 and random.random() < diagnosis.referral_probability * 0.3:
        await log_referral(user_id, "routine")
        return "如果想更深入探索，也可以考慮找諮商師聊聊 🌿"

    return ""


# ── 簽到補充 ──────────────────────────────────────────────────

async def handle_checkin_supplement(event, line_bot_api, session, text):
    from services.ai_label import analyze_checkin
    user_id = event.source.user_id
    reply_token = event.reply_token
    pending = session["pending_checkin"]

    if text == "跳過":
        await save_checkin(user_id, {
            "emotion": pending["emotion"],
            "timestamp": pending["timestamp"]
        })
        session.pop("pending_checkin")
        await save_session(user_id, session)
        await _reply(reply_token, "已記錄 ✓\n\n如果之後想聊聊，隨時傳訊息給我。", line_bot_api)
    else:
        result = await analyze_checkin(text, pending["emotion"])
        await save_checkin(user_id, {
            "emotion": pending["emotion"],
            "cognition": result.get("cognition"),
            "need": result.get("need"),
            "user_text": text,
            "timestamp": pending["timestamp"]
        })
        session.pop("pending_checkin")
        await save_session(user_id, session)
        reflection = result.get("reflection", "謝謝你願意說出來。")
        await _reply(reply_token, f"已記錄 ✓\n\n{reflection}", line_bot_api)


# ── 工具函式 ──────────────────────────────────────────────────

async def _reply(reply_token: str, text: str, line_bot_api: MessagingApi):
    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=text)]
        )
    )


async def send_welcome(reply_token: str, line_bot_api: MessagingApi):
    msg = (
        "嗨，我是心事日記 🌿\n\n"
        "我可以陪你整理心裡的想法，"
        "用提問的方式幫你看清楚困擾你的事。\n\n"
        "你可以：\n"
        "• 直接說出你在煩惱的事\n"
        "• 輸入「簽到」記錄今天的狀態\n"
        "• 輸入「說明」了解更多功能"
    )
    await _reply(reply_token, msg, line_bot_api)


async def send_help(reply_token: str, line_bot_api: MessagingApi):
    msg = (
        "📖 使用說明\n\n"
        "【開始對話】\n"
        "直接說出你的煩惱，我會陪你一起看清楚。\n\n"
        "【每日簽到】\n"
        "輸入「簽到」記錄今天的心情狀態。\n\n"
        "【隨時開始】\n"
        "不需要特別的格式，就像跟朋友說話一樣。"
    )
    await _reply(reply_token, msg, line_bot_api)


async def send_checkin_flex(reply_token: str, line_bot_api: MessagingApi):
    flex_content = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "今天的你，比較像哪一種？",
                 "weight": "bold", "size": "lg", "color": "#1D9E75"},
                {"type": "text", "text": "選一個最接近現在感受的選項",
                 "size": "sm", "color": "#888888", "margin": "sm"}
            ],
            "backgroundColor": "#F0FAF6",
            "paddingAll": "16px"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {"type": "button",
                 "action": {"type": "postback", "label": "😰 很崩潰，快撐不住了",
                            "data": "action=checkin&emotion=ACUTE_DISTRESS"},
                 "style": "secondary", "height": "sm"},
                {"type": "button",
                 "action": {"type": "postback", "label": "🔁 一件事一直在腦袋裡轉",
                            "data": "action=checkin&emotion=RUMINATION"},
                 "style": "secondary", "height": "sm"},
                {"type": "button",
                 "action": {"type": "postback", "label": "😞 覺得都是自己的錯",
                            "data": "action=checkin&emotion=SELF_BLAME"},
                 "style": "secondary", "height": "sm"},
                {"type": "button",
                 "action": {"type": "postback", "label": "😶 說不清楚，就是哪裡不對",
                            "data": "action=checkin&emotion=CONFUSION"},
                 "style": "secondary", "height": "sm"},
                {"type": "button",
                 "action": {"type": "postback", "label": "🧘 還好，心情比較平穩",
                            "data": "action=checkin&emotion=CALM_REFLECTIVE"},
                 "style": "primary", "color": "#1D9E75", "height": "sm"}
            ],
            "paddingAll": "16px"
        }
    }
    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[FlexMessage(
                alt_text="今天的你，比較像哪一種？",
                contents=FlexContainer.from_dict(flex_content)
            )]
        )
    )
