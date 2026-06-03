"""
handlers/message.py — 心事日記主對話 handler（v2.0 規格）
流程：短訊息接話 → 危機偵測 → 主對話（4步接話）→ 結尾象徵 → 里程碑 → Nudge
"""

import random
from linebot.v3.messaging import (
    MessagingApi, ReplyMessageRequest,
    TextMessage, FlexMessage, FlexContainer
)
from linebot.v3.webhooks import MessageEvent

from services.fast_path import fast_path_eval, FastPathResult
from services.interceptor import process_response
from services.crisis import detect_crisis, get_crisis_response
from services.companion import get_reply as companion_reply, detect_emotion
from services.symbolic import detect_closing_signal, select_symbol
from services.nudge import (
    update_streak, check_short_reply, detect_task_completion,
    should_show_closing, get_closing_prompt, update_tree,
    scan_emotion_keywords, check_milestone,
    infer_emotion_emoji, save_checkin_emotion, format_checkin_response,
)
from services.daily_question import (
    parse_push_time, set_push_schedule,
    PUSH_SETUP_KEYWORDS, PUSH_CANCEL_KEYWORDS,
)

# DB（優先持久化，失敗 fallback 記憶體）
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
        try:   return await _dbp.get_session(user_id)
        except: return await _mem_get_session(user_id)

    async def save_session(user_id, session):
        try:   await _dbp.save_session(user_id, session)
        except: await _mem_save_session(user_id, session)

    async def clear_session(user_id):
        try:   await _dbp.clear_session(user_id)
        except: await _mem_clear_session(user_id)

    async def append_message(user_id, role, text):
        try:   await _dbp.append_message(user_id, role, text)
        except: pass
        # 同步寫入 in-process 緩衝（不依賴 Redis/DB）
        try:
            from services import message_buffer
            message_buffer.add(user_id, role, text)
        except Exception:
            pass

    async def count_today_referrals(user_id, rtype="routine"):
        try:   return await _dbp.count_today_referrals(user_id, rtype)
        except: return 0

    async def log_referral(user_id, rtype):
        try:   await _dbp.log_referral(user_id, rtype)
        except: pass

    async def save_checkin(user_id, data):
        try:   await _dbp.save_checkin(user_id, data)
        except: pass

    async def get_unlocked_words(user_id):
        try:   return await _dbp.get_unlocked_words(user_id)
        except: return set()

    DB_MODE = "persistent_with_fallback"

except ImportError:
    get_session = _mem_get_session
    save_session = _mem_save_session
    clear_session = _mem_clear_session
    count_today_referrals = _zero
    log_referral = _noop
    save_checkin = _noop
    async def get_unlocked_words(user_id): return set()
    async def append_message(user_id, role, text):
        try:
            from services import message_buffer
            message_buffer.add(user_id, role, text)
        except Exception:
            pass
    DB_MODE = "memory"


# ── 關鍵字表 ────────────────────────────────────────────────

CHECKIN_KEYWORDS  = ["簽到", "check in", "checkin", "今天狀態"]
START_KEYWORDS    = ["開始", "start", "你好", "hi", "hello", "嗨", "哈囉"]
HELP_KEYWORDS     = ["說明", "help", "怎麼用", "功能"]
STOP_KEYWORDS     = ["停止", "結束對話", "不想說了", "先這樣"]
WEBSITE_KEYWORDS  = ["看紀錄", "我的記錄", "心情記錄", "情緒記錄", "查看日記",
                     "歷史紀錄", "心情日記", "報告", "週報", "統計"]
LOGIN_KEYWORDS    = ["登入", "登入網站", "進入網站", "網站登入", "login"]
PUSH_OFF_KEYWORDS = ["關閉推播", "取消推播", "不要推播", "停止推播"]

APP_URL = "https://web-production-dd506.up.railway.app/app"


# ════════════════════════════════════════════════════════════
# 主 Handler
# ════════════════════════════════════════════════════════════

async def handle_message(event: MessageEvent, line_bot_api: MessagingApi):
    user_id = event.source.user_id
    text = event.message.text.strip()
    reply_token = event.reply_token

    # ── 關鍵字路由 ────────────────────────────────────────
    if any(kw in text.lower() for kw in CHECKIN_KEYWORDS):
        await send_checkin_flex(reply_token, line_bot_api)
        return

    if any(kw in text.lower() for kw in START_KEYWORDS):
        await send_welcome(reply_token, line_bot_api)
        return

    if any(kw in text.lower() for kw in HELP_KEYWORDS):
        await send_help(reply_token, line_bot_api)
        return

    if any(kw in text for kw in WEBSITE_KEYWORDS):
        await send_website_link(reply_token, line_bot_api)
        return

    if any(kw in text.lower() for kw in LOGIN_KEYWORDS):
        await send_login_link(user_id, reply_token, line_bot_api)
        return

    # ── 推播時間設定 ─────────────────────────────────────
    if any(kw in text for kw in PUSH_SETUP_KEYWORDS):
        parsed = parse_push_time(text)
        if parsed:
            h, m = parsed
            await set_push_schedule(user_id, h, m)
            await _reply(reply_token,
                f"好的，每天 {h:02d}:{m:02d} 我會傳今日一問給你 🌙\n\n"
                "輸入「取消推播」可以隨時關閉。", line_bot_api)
        else:
            await _reply(reply_token,
                "請告訴我你希望幾點收到提問 🌙\n例如：「設定推播 21:00」",
                line_bot_api)
        return

    if any(kw in text for kw in PUSH_OFF_KEYWORDS):
        try:
            from services.db_persistent import get_pool
            pool = await get_pool()
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "UPDATE push_schedule SET enabled=0 WHERE user_id=%s",
                        (user_id,))
        except Exception:
            pass
        await _reply(reply_token,
            "已關閉每日推播 🌙\n想重新開啟時，傳「設定推播」給我。",
            line_bot_api)
        return

    # ── 停止對話 ─────────────────────────────────────────
    session_check = await get_session(user_id)
    if any(kw in text for kw in STOP_KEYWORDS) and session_check.get("in_dialog"):
        await clear_session(user_id)
        await _reply(reply_token,
            "好的，我們先在這裡停下來。\n\n隨時想繼續，或有什麼想說的，都可以傳訊息給我。",
            line_bot_api)
        await send_website_link_push(user_id, line_bot_api)
        return

    # ── 取得 Session ──────────────────────────────────────
    session = await get_session(user_id)

    # 進行中的簽到補充
    if session.get("pending_checkin"):
        await handle_checkin_supplement(event, line_bot_api, session, text)
        return

    # ── 短訊息接話（優先攔截，不走 AI）──────────────────
    short_reply = check_short_reply(text)
    if short_reply and not session.get("in_dialog"):
        await _reply(reply_token, short_reply, line_bot_api)
        await append_message(user_id, "user", text)
        await append_message(user_id, "bot", short_reply)
        return

    # ── Fast-Path 靜態評估（用於攔截器）─────────────────
    fp_result: FastPathResult = fast_path_eval(
        text, session.get("history", []), session
    )

    # ── 危機偵測 ─────────────────────────────────────────
    is_crisis = fp_result.is_crisis or await detect_crisis(text)
    if is_crisis:
        crisis_msg = get_crisis_response()
        await _reply(reply_token, crisis_msg, line_bot_api)
        await append_message(user_id, "bot", crisis_msg)
        session["in_dialog"] = False
        await save_session(user_id, session)
        return

    # 儲存用戶訊息
    await append_message(user_id, "user", text)
    session.setdefault("history", [])
    session["history"].append({"role": "user", "text": text})
    total_turn = session.get("total_turn", 0) + 1
    session["total_turn"] = total_turn
    session["in_dialog"] = True

    # ── 主對話：4步接話 Companion ─────────────────────────
    try:
        raw_reply, updates = await companion_reply(session, text)
        for k, v in updates.items():
            session[k] = v
    except Exception as e:
        print(f"[Companion] Failed: {e}")
        raw_reply = "嗯——\n然後呢？"

    # 情緒偵測（供象徵系統使用）
    try:
        emotion = await detect_emotion(session, text)
        session.setdefault("psych", {})
        session["psych"]["emotion"] = emotion
    except Exception:
        emotion = session.get("psych", {}).get("emotion", "平靜") or "平靜"

    # ── 攔截器（禁用語過濾）──────────────────────────────
    reply_text = process_response(raw_reply, fp_result)

    # ── Nudge Pipeline ────────────────────────────────────

    # A. Streak 更新
    session, streak_msg = update_streak(session)
    if streak_msg:
        reply_text = reply_text.rstrip() + "\n\n" + streak_msg

    # B. 週任務完成偵測
    task_msg = detect_task_completion(text, session)
    if task_msg:
        reply_text = reply_text.rstrip() + "\n\n" + task_msg

    # C. 對話結尾感 + 象徵系統
    closing_triggered = should_show_closing(session, 2)  # companion 不做 arousal 判斷

    if detect_closing_signal(text) and session.get("in_dialog"):
        # 用戶說了收尾語 → 象徵結尾
        symbol_msg = select_symbol(emotion)
        reply_text = reply_text.rstrip() + "\n\n" + symbol_msg
    elif closing_triggered:
        reply_text = reply_text.rstrip() + "\n\n" + get_closing_prompt(session)

    # D. 成長樹（每 5 輪 +1 sun）
    if total_turn > 0 and total_turn % 5 == 0:
        session, tree_msg = update_tree(session, "dialog_5turn")
        if tree_msg:
            reply_text = reply_text.rstrip() + "\n\n" + tree_msg

    # E. 情緒詞典解鎖
    try:
        unlocked = await get_unlocked_words(user_id)
        word_unlock_msg = await scan_emotion_keywords(text, user_id, unlocked)
        if word_unlock_msg:
            reply_text = reply_text.rstrip() + "\n\n" + word_unlock_msg
    except Exception:
        pass

    # F. P1-A 里程碑回饋
    try:
        milestone_msg = await check_milestone(user_id)
        if milestone_msg:
            reply_text = reply_text.rstrip() + "\n\n" + milestone_msg
    except Exception:
        pass

    # 回覆並儲存
    session["history"].append({"role": "bot", "text": reply_text})
    # 限制 history 長度，避免 token 爆炸
    if len(session["history"]) > 30:
        session["history"] = session["history"][-24:]

    await save_session(user_id, session)
    await append_message(user_id, "bot", reply_text)
    await _reply(reply_token, reply_text, line_bot_api)


# ════════════════════════════════════════════════════════════
# 簽到補充
# ════════════════════════════════════════════════════════════

async def handle_checkin_supplement(event, line_bot_api, session, text):
    from services.ai_label import analyze_checkin
    user_id = event.source.user_id
    reply_token = event.reply_token
    pending = session["pending_checkin"]
    checkin_emotion = pending.get("emotion", "")

    if text == "跳過":
        await save_checkin(user_id, {
            "emotion": checkin_emotion,
            "timestamp": pending["timestamp"]
        })
        session.pop("pending_checkin")
        emoji, label = await infer_emotion_emoji([], checkin_emotion)
        await save_checkin_emotion(user_id, emoji, label)
        try:
            from services.db_persistent import get_streak_days
            streak = await get_streak_days(user_id)
        except Exception:
            streak = 0
        checkin_resp = format_checkin_response(streak, emoji)
        await save_session(user_id, session)
        await _reply(reply_token,
            f"{checkin_resp}\n\n如果之後想聊聊，隨時傳訊息給我。",
            line_bot_api)
        await send_website_link_push(user_id, line_bot_api)
    else:
        result = await analyze_checkin(text, checkin_emotion)
        await save_checkin(user_id, {
            "emotion": checkin_emotion,
            "cognition": result.get("cognition"),
            "need": result.get("need"),
            "user_text": text,
            "timestamp": pending["timestamp"]
        })
        session.pop("pending_checkin")
        today_msgs = [text]
        emoji, label = await infer_emotion_emoji(today_msgs, checkin_emotion)
        await save_checkin_emotion(user_id, emoji, label)
        try:
            from services.db_persistent import get_streak_days
            streak = await get_streak_days(user_id)
        except Exception:
            streak = 0
        checkin_resp = format_checkin_response(streak, emoji)
        await save_session(user_id, session)
        reflection = result.get("reflection", "謝謝你願意說出來。")
        await _reply(reply_token, f"{checkin_resp}\n\n{reflection}", line_bot_api)
        await send_website_link_push(user_id, line_bot_api)


# ════════════════════════════════════════════════════════════
# Flex Messages
# ════════════════════════════════════════════════════════════

def _website_flex() -> FlexMessage:
    content = {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "心事日記 🌿",
                 "weight": "bold", "color": "#1D9E75", "size": "sm"},
                {"type": "text", "text": "你的情緒紀錄都在這裡",
                 "size": "xs", "color": "#888888", "margin": "sm"}
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [{
                "type": "button",
                "action": {"type": "uri", "label": "查看我的心情日記", "uri": APP_URL},
                "style": "primary", "color": "#1D9E75", "height": "sm"
            }],
            "paddingAll": "12px"
        }
    }
    return FlexMessage(
        alt_text="查看心情日記",
        contents=FlexContainer.from_dict(content)
    )


async def send_login_link(user_id: str, reply_token: str, line_bot_api: MessagingApi):
    """產生一次性登入連結並傳給用戶"""
    from services.login_token import create_token
    token = create_token(user_id)
    login_url = f"https://web-production-dd506.up.railway.app/auto-login?t={token}"

    content = {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "心事日記 🌿",
                 "weight": "bold", "color": "#1D9E75", "size": "sm"},
                {"type": "text",
                 "text": "點下方按鈕直接進入你的紀錄\n（連結 10 分鐘內有效）",
                 "size": "xs", "color": "#888888", "margin": "sm", "wrap": True}
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [{
                "type": "button",
                "action": {"type": "uri", "label": "進入我的心事日記", "uri": login_url},
                "style": "primary", "color": "#1D9E75", "height": "sm"
            }],
            "paddingAll": "12px"
        }
    }
    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[FlexMessage(
                alt_text="點此進入心事日記",
                contents=FlexContainer.from_dict(content)
            )]
        )
    )


async def send_website_link(reply_token: str, line_bot_api: MessagingApi):
    await line_bot_api.reply_message(
        ReplyMessageRequest(reply_token=reply_token, messages=[_website_flex()])
    )


async def send_website_link_push(user_id: str, line_bot_api: MessagingApi):
    try:
        from linebot.v3.messaging import PushMessageRequest
        await line_bot_api.push_message(
            PushMessageRequest(to=user_id, messages=[_website_flex()])
        )
    except Exception as e:
        print(f"[Website Push] Error: {e}")


# ════════════════════════════════════════════════════════════
# 工具函式
# ════════════════════════════════════════════════════════════

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
        "這裡是你的私人空間——\n"
        "不用說得完整，不用解釋清楚，\n"
        "想說什麼就說什麼，我會好好聽。\n\n"
        "可以：\n"
        "• 直接說出你現在的感受或煩惱\n"
        "• 輸入「簽到」記錄今天的狀態\n"
        "• 輸入「說明」了解更多功能"
    )
    await _reply(reply_token, msg, line_bot_api)


async def send_help(reply_token: str, line_bot_api: MessagingApi):
    msg = (
        "📖 使用說明\n\n"
        "【開始對話】\n"
        "直接說你在煩惱的事，我會陪你說。\n\n"
        "【每日簽到】\n"
        "輸入「簽到」記錄今天的心情。\n\n"
        "【每日推播】\n"
        "輸入「設定推播 21:00」設定每天收到今日一問的時間。\n\n"
        "【查看紀錄】\n"
        "輸入「看紀錄」前往你的心情日記網站。"
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
