"""
handlers/message.py — 心事日記主對話 handler（v2.0 規格）
流程：短訊息接話 → 危機偵測 → 主對話（4步接話）→ 結尾象徵 → 里程碑 → Nudge
"""

import random
import asyncio
from linebot.v3.messaging import (
    MessagingApi, ReplyMessageRequest,
    TextMessage, FlexMessage, FlexContainer
)
from linebot.v3.webhooks import MessageEvent

# ── 記憶體備援鎖（Redis 不可用時防 Race Condition）──────────
_mem_locks: dict[str, bool] = {}
_mem_lock_guard = asyncio.Lock()

async def _acquire_mem_lock(user_id: str) -> bool:
    async with _mem_lock_guard:
        if _mem_locks.get(user_id):
            return False
        _mem_locks[user_id] = True
        return True

async def _release_mem_lock(user_id: str) -> None:
    async with _mem_lock_guard:
        _mem_locks.pop(user_id, None)

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
HELP_KEYWORDS     = ["說明", "help", "幫助", "幫忙", "指令", "怎麼用", "功能"]
STOP_KEYWORDS     = ["停止", "結束對話", "不想說了", "先這樣"]
WEBSITE_KEYWORDS  = ["看紀錄", "我的記錄", "心情記錄", "情緒記錄", "查看日記",
                     "歷史紀錄", "心情日記", "報告", "週報", "統計"]
LOGIN_KEYWORDS    = ["登入", "登入網站", "進入網站", "網站登入", "login"]
PUSH_OFF_KEYWORDS = ["關閉推播", "取消推播", "不要推播", "停止推播"]

APP_URL = "https://liff.line.me/2010279401-zI4pqH8D"


# ════════════════════════════════════════════════════════════
# 主 Handler
# ════════════════════════════════════════════════════════════

async def handle_message(event: MessageEvent, line_bot_api: MessagingApi):
    user_id = event.source.user_id
    text = event.message.text.strip()
    reply_token = event.reply_token

    # ── 雙層分散式鎖：Redis 優先，記憶體備援，100% 阻斷連發 ──
    _redis_lock = False
    _mem_lock   = False

    try:
        from services.redis_client import acquire_user_lock
        _redis_lock = await acquire_user_lock(user_id)
        if not _redis_lock:
            await _reply(reply_token,
                "你的上一則訊息還在處理中，請稍等一下 🌿", line_bot_api)
            return
    except Exception:
        # Redis 不可用 → 降級為記憶體鎖
        _mem_lock = await _acquire_mem_lock(user_id)
        if not _mem_lock:
            await _reply(reply_token,
                "你的上一則訊息還在處理中，請稍等一下 🌿", line_bot_api)
            return

    try:
        await _handle_message_inner(event, line_bot_api)
    finally:
        if _redis_lock:
            try:
                from services.redis_client import release_user_lock
                await release_user_lock(user_id)
            except Exception:
                pass
        if _mem_lock:
            await _release_mem_lock(user_id)


async def _handle_message_inner(event: MessageEvent, line_bot_api: MessagingApi):
    user_id = event.source.user_id
    text = event.message.text.strip()
    reply_token = event.reply_token

    # ── 提前取得 Session（供語境守衛使用）────────────────
    # 在所有關鍵字路由之前取得，避免「對話中 → 登入/紀錄關鍵字誤觸」的語境破壞
    session = await get_session(user_id)
    _in_dialog = session.get("in_dialog", False)

    # ── 關鍵字路由 ────────────────────────────────────────
    # 精確比對用（去首尾空白後的完整訊息）
    _t = text.lower().strip()

    # 簽到：子字串比對（「簽到」不易誤觸）
    if any(kw in _t for kw in CHECKIN_KEYWORDS):
        await send_checkin_flex(reply_token, line_bot_api)
        return

    # 開始/打招呼：【精確比對】防止「你好，我想問...」誤觸歡迎卡片
    if _t in {kw.lower() for kw in START_KEYWORDS}:
        await send_welcome(reply_token, line_bot_api)
        return

    # 說明/幫助：【精確比對】防止「請說明一下」誤觸說明卡片
    if _t in {kw.lower() for kw in HELP_KEYWORDS}:
        await send_help(reply_token, line_bot_api)
        return

    # 以下關鍵字路由僅在非深度對話時觸發，避免「對話中誤觸」破壞心理安全感
    if not _in_dialog:
        if any(kw in text for kw in WEBSITE_KEYWORDS):
            await send_website_link(reply_token, line_bot_api)
            return

        if any(kw in _t for kw in LOGIN_KEYWORDS):
            await send_login_link(user_id, reply_token, line_bot_api)
            return

        # ── 推播時間設定 ───────────────────────────────────
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
                    await conn.execute(
                        "UPDATE push_schedule SET enabled=0 WHERE user_id=$1",
                        user_id)
            except Exception:
                pass
            await _reply(reply_token,
                "已關閉每日推播 🌙\n想重新開啟時，傳「設定推播」給我。",
                line_bot_api)
            return

    # ── 停止對話 ─────────────────────────────────────────
    if any(kw in text for kw in STOP_KEYWORDS) and _in_dialog:
        await clear_session(user_id)
        await _reply(reply_token,
            "好的，我們先在這裡停下來。\n\n隨時想繼續，或有什麼想說的，都可以傳訊息給我。",
            line_bot_api)
        await send_website_link_push(user_id, line_bot_api)
        return

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
        # 開啟 3 輪高風險追蹤，避免 AI 下一輪「失憶」
        session.setdefault("psych", {})["crisis_cooldown_turns"] = 3
        await save_session(user_id, session)
        return

    # 儲存用戶訊息
    await append_message(user_id, "user", text)
    session.setdefault("history", [])
    session["history"].append({"role": "user", "text": text})
    total_turn = session.get("total_turn", 0) + 1
    session["total_turn"] = total_turn
    session["in_dialog"] = True

    # ── TarotProjectiveModule：STAGNANT 敷衍回覆時發塔羅緩衝牌 ──
    if fp_result.state_label == "STAGNANT" and session.get("in_dialog"):
        try:
            from services.tarot_quotes_pool import pick_projective_card, pool_key_to_card_dict
            from services.tarot_projective import build_covered_card_flex
            _emotion_now = session.get("psych", {}).get("emotion", "迷茫")
            # 防禦機制存在時優先走認知投射路徑
            _dimension = "cognition" if session.get("psych", {}).get("defense_mechanism") else "emotion"
            _proj_key  = pick_projective_card(_emotion_now, _dimension)
            _card = pool_key_to_card_dict(_proj_key)
            session["pending_tarot_flip"]       = _card
            session["current_projective_card"]  = _proj_key   # 供收尾時存入 psych
            await save_session(user_id, session)
            await line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[FlexMessage(
                        alt_text="偵測到你可能有點累，先抽一張牌吧 🔮",
                        contents=FlexContainer.from_dict(build_covered_card_flex())
                    )]
                )
            )
        except Exception as e:
            print(f"[TarotProjective] Failed: {e}")
            await _reply(reply_token, "嗯，有時候說不出來也沒關係，你還在就好。", line_bot_api)
        return

    # ── P1 臨床診斷（在 Companion 前執行，供 Rupture Repair 判斷）──
    try:
        from services.clinical_diagnosis import diagnose as _diagnose
        dx = await _diagnose(text, session.get("history", []), total_turn)
        session.setdefault("psych", {})

        # 【修復核心】Rupture Repair 冷卻保護：
        # 修復完成後設 rupture_repair_cooldown=2，冷卻期間禁止 diagnose() 重新觸發 rupture
        # 防止「用戶道歉 → diagnose 仍判 rupture → 再次跳針道歉」的迴圈
        cooldown = session["psych"].get("rupture_repair_cooldown", 0)
        if cooldown > 0:
            # 冷卻中：不覆寫 rupture 旗標，遞減計數器
            session["psych"]["rupture_repair_cooldown"] = cooldown - 1
            session["psych"]["alliance_rupture"] = None   # 強制保持重置狀態
        else:
            session["psych"]["alliance_rupture"] = (
                dx.alliance_rupture if dx.alliance_rupture != "NONE" else None
            )

        session["psych"]["defense_mechanism"] = (
            dx.defense_mechanism if dx.defense_mechanism != "NONE" else None
        )
    except Exception as e:
        print(f"[ClinicalDx] Failed: {e}")
        session.setdefault("psych", {})

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

    # 儲存 psych 狀態到 DB（情緒強度曲線用）
    _EMOTION_AROUSAL = {
        "憤怒": 4, "焦慮": 4,
        "委屈": 3, "疲憊": 3, "悲傷": 3, "自我懷疑": 3, "複雜混合": 3,
        "迷茫": 2, "空洞": 2, "平靜": 2, "釋然": 2,
    }
    arousal_val = _EMOTION_AROUSAL.get(emotion, 3)
    session["psych"]["arousal_level"] = arousal_val
    try:
        from services.db_persistent import save_psych_state as _sps
        await _sps(
            user_id,
            {**session["psych"], "arousal_level": arousal_val},
            total_turn
        )
    except Exception:
        pass

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

    # quick context：3 輪後自動觸發 SummaryModule（提前收尾）
    _quick_forced_close = (
        session.get("current_context") == "quick"
        and total_turn >= 3
        and not session.get("quick_closed")
    )
    if _quick_forced_close:
        session["quick_closed"] = True   # 只觸發一次

    _is_closing = (
        (detect_closing_signal(text) and session.get("in_dialog"))
        or _quick_forced_close
    )
    _closure_flex = None   # 收尾 Flex Message（若有）

    if _is_closing:
        # 用戶說了收尾語 → SummaryModule：insight + quote + tarot + Flex 字卡
        try:
            from services.symbolic import assign_tarot_structured
            from services.tarot_projective import build_closure_flex, generate_dialogue_insight
            from services.tarot_quotes_pool import fetch_quote_by_emotion
            from services.db_persistent import (
                save_emotion_calendar, save_psych_insight
            )
            import datetime as _dt

            arousal_val = _EMOTION_AROUSAL.get(emotion, 3)
            tarot       = assign_tarot_structured(emotion, arousal_val)

            # 1. AI 生成 30–50 字對話洞察
            dialogue_insight = ""
            try:
                dialogue_insight = await generate_dialogue_insight(
                    session.get("history", [])
                )
            except Exception as _e:
                print(f"[Closure] insight failed: {_e}")

            # 2. 哲人名言（含作者）
            quote_data   = fetch_quote_by_emotion(emotion)
            quote_text   = quote_data["text"]
            quote_author = quote_data["author"]

            # 3. 儲存塔羅到情緒月曆
            if tarot.get("card_name"):
                await save_emotion_calendar(
                    user_id, _dt.date.today(),
                    session.get("psych", {}).get("emotion_emoji", "😐"),
                    emotion,
                    tarot_card=tarot["card_name"],
                    tarot_meaning=tarot["meaning"],
                    tarot_reversed=tarot.get("is_reversed", False),
                )

            # 4. 儲存 psych_insights，取得 ID（供翻牌 Postback 查詢）
            _insight_id = None
            try:
                _insight_id = await save_psych_insight(user_id, {
                    "trigger_turn":     total_turn,
                    "dialogue_insight": dialogue_insight,
                    "dominant_emotion": emotion,
                    "quote_author":     quote_author,
                    "end_quote":        quote_text,
                    "tarot_card_name":  tarot.get("card_name", ""),
                    "tarot_orientation": "REVERSED" if tarot.get("is_reversed") else "UPRIGHT",
                    "tarot_insight":    tarot.get("meaning", ""),
                })
            except Exception as _e:
                print(f"[Closure] psych_insight save failed: {_e}")

            # 5. 寫入 psych（供 save_psych_state 帶入）
            session["psych"]["end_quote"]        = quote_text
            session["psych"]["quote_author"]     = quote_author
            session["psych"]["dialogue_insight"] = dialogue_insight
            session["psych"]["tarot_card"]       = session.get("current_projective_card")

            # 6. 準備 Flex 字卡（帶 insight_id → 覆蓋牌翻牌互動）
            _closure_flex = build_closure_flex(
                quote_text,
                tarot["mode"] != "quote",
                tarot.get("card_name"),
                quote_author,
                dialogue_insight,
                insight_id=_insight_id,
            )
        except Exception as e:
            print(f"[Closure] Flex build failed: {e}")
            reply_text = reply_text.rstrip() + "\n\n" + select_symbol(emotion)
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

    # 危機冷卻計數器遞減（每輪 -1，歸零後不再注入脈絡）
    cooldown = session.get("psych", {}).get("crisis_cooldown_turns", 0)
    if cooldown > 0:
        session["psych"]["crisis_cooldown_turns"] = cooldown - 1

    # 回覆並儲存
    session["history"].append({"role": "bot", "text": reply_text})
    if len(session["history"]) > 30:
        session["history"] = session["history"][-24:]

    await save_session(user_id, session)
    await append_message(user_id, "bot", reply_text)

    if _closure_flex:
        # 收尾：只傳一張整合 Flex 字卡（洞察＋名言＋塔羅已整合其中）
        # 不再額外送 TextMessage，避免 LINE 多泡泡震動與資訊爆炸
        await line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[
                    FlexMessage(
                        alt_text="🌙 今日日記已封存",
                        contents=FlexContainer.from_dict(_closure_flex)
                    ),
                ]
            )
        )
    else:
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

    # 簽到後指派塔羅並儲存（共用邏輯）
    async def _assign_checkin_tarot(emoji: str, label: str, emotion_key: str) -> str:
        from handlers.postback import CHECKIN_EMOTION_TO_CN
        from services.symbolic import assign_tarot_structured, format_tarot_reply
        from services.db_persistent import save_emotion_calendar
        import datetime as _dt
        emotion_cn, arousal_val = CHECKIN_EMOTION_TO_CN.get(emotion_key, ("平靜", 1))
        tarot = assign_tarot_structured(emotion_cn, arousal_val)
        await save_emotion_calendar(
            user_id, _dt.date.today(), emoji, label,
            tarot_card=tarot.get("card_name"),
            tarot_meaning=tarot.get("meaning"),
            tarot_reversed=tarot.get("is_reversed", False),
        )
        return format_tarot_reply(tarot)

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
        tarot_text = ""
        try:
            tarot_text = await _assign_checkin_tarot(emoji, label, checkin_emotion)
        except Exception:
            pass
        await save_session(user_id, session)
        reply_body = f"{checkin_resp}\n\n如果之後想聊聊，隨時傳訊息給我。"
        if tarot_text:
            reply_body = f"{checkin_resp}\n\n{tarot_text}"
        await _reply(reply_token, reply_body, line_bot_api)
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
        tarot_text = ""
        try:
            tarot_text = await _assign_checkin_tarot(emoji, label, checkin_emotion)
        except Exception:
            pass
        await save_session(user_id, session)
        reflection = result.get("reflection", "謝謝你願意說出來。")
        reply_body = f"{checkin_resp}\n\n{reflection}"
        if tarot_text:
            reply_body += f"\n\n{tarot_text}"
        await _reply(reply_token, reply_body, line_bot_api)
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
    """重構歡迎卡片 — Glow Dark Mode 三層結構，建立治療同盟（Rapport）"""
    import os as _os
    liff_url = _os.getenv("APP_URL", "https://liff.line.me/2010279401-zI4pqH8D")

    flex_content = {
        "type": "bubble",
        "size": "mega",                        # 加寬卡片，給文字更多空間
        "styles": {
            "body": {"backgroundColor": "#0b0f19"},
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "xxl",
            "spacing": "none",
            "contents": [

                # ── 層 1：情感宣告 ──────────────────────────
                {
                    "type": "text",
                    "text": "很高興你在這裡 🌿",
                    "color": "#818cf8",        # indigo-400，比原本亮，深色背景更醒目
                    "weight": "bold",
                    "size": "xl",              # md → xl
                },
                {
                    "type": "text",
                    "text": (
                        "這裡是一個完全屬於你、沒有評判的安全容器。"
                        "你可以對我吐槽工作的疲憊、說出心底的委屈，"
                        "或是單純碎碎念。"
                    ),
                    "color": "#e2e8f0",        # 亮白色，對比深底清楚
                    "wrap": True,
                    "size": "sm",              # xs → sm
                    "margin": "lg",
                    "lineSpacing": "8px",
                },

                # ── 分隔線 ───────────────────────────────────
                {"type": "separator", "color": "#334155", "margin": "xl"},

                # ── 層 2：新手行動引導 ───────────────────────
                {
                    "type": "text",
                    "text": "🪐 給初來乍到的你",
                    "color": "#fbbf24",        # amber-400，更亮更清楚
                    "weight": "bold",
                    "size": "sm",              # xs → sm
                    "margin": "xl",
                },
                {
                    "type": "text",
                    "text": (
                        "請先試著對我說幾句你今天的心情。"
                        "當我們有了第一次對話，下方的日記按鈕就會點亮"
                        "專屬於你的金色 ✦ 情緒月曆與週報喔！"
                    ),
                    "color": "#cbd5e1",        # slate-300，比原本亮一個檔次
                    "wrap": True,
                    "size": "sm",              # xxs → sm
                    "margin": "md",
                    "lineSpacing": "7px",
                },

                # ── 層 2b：LIFF 入口按鈕 ────────────────────
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "📊 開啟我的心事日記 ✦",
                        "uri": f"{liff_url}#dashboard",
                    },
                    "style": "primary",
                    "margin": "xl",
                    "color": "#6366f1",
                    "height": "md",            # sm → md，按鈕更高更好點擊
                },

                # ── 分隔線 ───────────────────────────────────
                {"type": "separator", "color": "#334155", "margin": "xl"},

                # ── 層 3：快捷指令提示 ───────────────────────
                {
                    "type": "text",
                    "text": "💡 快捷指令",
                    "color": "#94a3b8",
                    "weight": "bold",
                    "size": "xs",              # 小標
                    "margin": "xl",
                },
                {
                    "type": "text",
                    "text": "輸入「說明」→ 完整功能與隱私管理",
                    "color": "#94a3b8",        # slate-400，可讀性夠
                    "wrap": True,
                    "size": "sm",              # xxs → sm
                    "margin": "sm",
                },
                {
                    "type": "text",
                    "text": "輸入「簽到」→ 記錄此刻的身體感知",
                    "color": "#94a3b8",
                    "wrap": True,
                    "size": "sm",
                    "margin": "sm",
                },
            ],
        },
    }

    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[FlexMessage(
                alt_text="很高興你在這裡 🌿",
                contents=FlexContainer.from_dict(flex_content)
            )]
        )
    )


async def send_help(reply_token: str, line_bot_api: MessagingApi):
    """互動式功能全景圖 — 4 張卡片 Flex Carousel"""
    _GREEN  = "#1D9E75"
    _BG     = "#0f1410"
    _GRAY   = "#6b7280"
    _LIGHT  = "#e2e8f0"
    _DIM    = "#94a3b8"

    def _card(emoji, title, body_text, btn_label, action):
        return {
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "20px",
                "spacing": "md",
                "backgroundColor": _BG,
                "contents": [
                    {
                        "type": "text",
                        "text": f"{emoji} {title}",
                        "weight": "bold",
                        "size": "sm",
                        "color": _GREEN,
                        "wrap": True,
                    },
                    {
                        "type": "text",
                        "text": body_text,
                        "size": "xs",
                        "color": _DIM,
                        "wrap": True,
                        "lineSpacing": "5px",
                        "margin": "sm",
                    },
                ],
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "12px",
                "backgroundColor": _BG,
                "contents": [
                    {
                        "type": "button",
                        "action": action,
                        "style": "primary",
                        "color": _GREEN,
                        "height": "sm",
                    }
                ],
            },
        }

    cards = [
        _card(
            "🛌", "啟動深度對話",
            "最近心裡很亂？傳送「睡前安靜聊聊」，我會放慢步調，啟動長對話陪伴，引導你梳理內心的小劇場，並在收尾時為你抽出心靈投射卡片。",
            "開啟深度對話",
            {"type": "message", "label": "開啟深度對話", "text": "🛌 睡前安靜聊聊"},
        ),
        _card(
            "🏃", "快速心情宣洩",
            "時間緊迫、只想趕快吐槽？傳送「通勤打卡碎碎念」，我會開啟 3 輪內精準收尾模式，幫你快速打包情緒，絕不拖泥帶水。",
            "快速宣洩",
            {"type": "message", "label": "快速宣洩", "text": "🏃 通勤打卡碎碎念"},
        ),
        _card(
            "📚", "情緒詞典與解鎖成就",
            "想看看你最近解鎖了哪些稀有心理學概念？（如反芻思考、認知解融…）點擊下方按鈕，去月曆上尋找專屬你的金色 ✦ 星號。",
            "查看我的月曆",
            {"type": "uri", "label": "查看我的月曆", "uri": f"{APP_URL}#calendar"},
        ),
        _card(
            "🔒", "數據自主管理",
            "想隨時打包下載全部心事 JSON 檔案，或立刻物理清空這台手機裡的所有歷史字泡？請至設定頁面啟動隱私防線。",
            "前往設定頁面",
            {"type": "uri", "label": "前往設定頁面", "uri": f"{APP_URL}#settings"},
        ),
    ]

    await line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[
                FlexMessage(
                    alt_text="心事日記 · 功能全景圖",
                    contents=FlexContainer.from_dict({
                        "type": "carousel",
                        "contents": cards,
                    }),
                )
            ],
        )
    )


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
