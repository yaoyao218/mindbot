"""
Nudge 系統 — 互動體驗強化模組
依照 mindbot_full_spec.docx v2.0 實作

功能：
  1. Streak 連續記錄火焰
  2. 每週小任務
  3. 對話結尾感
  4. 情緒個性接話（SHORT_REPLIES）
  5. 成長樹系統
  6. 情緒詞典解鎖
  7. 天氣描述（依 Arousal 歷史）
  8. P1-A 里程碑回饋（7/14/30 天）
  9. P1-B 情緒關鍵字個性接話擴充
"""

import random
from datetime import date, timedelta
from typing import Optional


# ════════════════════════════════════════════════════════
# 1. STREAK 連續記錄火焰
# ════════════════════════════════════════════════════════

MILESTONES = {7, 14, 30, 60, 100}

STREAK_MESSAGES = {
    1:   "🌙 今天重新點燃了記錄的火焰",
    3:   "🔥 連續 3 天了，你在建立一個習慣",
    7:   "🔥 連續 7 天——這週你每天都來了\n這不是小事。",
    14:  "🔥🔥 兩週連續記錄\n你現在說的話，和第一天很不一樣了",
    30:  "💎 30 天\n一個月前你開始說話\n現在你還在\n這就是答案",
    60:  "💎💎 60 天——你已經把這件事變成生活的一部分了",
    100: "✨ 100 天\n你做到了一件很多人沒做到的事：持續誠實地看自己",
}


def update_streak(session: dict) -> tuple[dict, Optional[str]]:
    """
    更新 streak 並回傳（更新後 session, 要附加的訊息）
    訊息為 None 代表今天已更新或無需附加
    """
    today = date.today()
    last_day_str = session.get("streak_last_day")
    streak = session.get("streak_count", 0)

    if last_day_str:
        last_day = date.fromisoformat(last_day_str)
        if last_day == today:
            # 今天已更新，不重複
            return session, None
        elif last_day == today - timedelta(days=1):
            streak += 1
        else:
            gap = (today - last_day).days
            # 中斷回來
            old_streak = streak
            streak = 1
            session["streak_count"] = streak
            session["streak_last_day"] = today.isoformat()
            if old_streak >= 3:
                msg = f"🌙 歡迎回來，隔了 {gap} 天\n你的火焰暫時休息了一下\n今天重新開始？"
                return session, msg
            return session, None
    else:
        streak = 1

    session["streak_count"] = streak
    session["streak_last_day"] = today.isoformat()

    # 每天只顯示一次 streak 訊息
    if session.get("streak_shown_today") == today.isoformat():
        return session, None
    session["streak_shown_today"] = today.isoformat()

    # 里程碑 > 一般文字
    msg = STREAK_MESSAGES.get(streak)
    if msg:
        return session, msg

    # 非里程碑：每5天顯示一次「你已連續 N 天」
    if streak > 1 and streak % 5 == 0:
        return session, f"🔥 連續 {streak} 天了"

    return session, None


def get_streak_status(session: dict) -> str:
    streak = session.get("streak_count", 0)
    if streak == 0:
        return "還沒有記錄 🌱"
    return f"🔥 連續 {streak} 天"


# ════════════════════════════════════════════════════════
# 2. 每週小任務
# ════════════════════════════════════════════════════════

WEEKLY_TASKS = [
    {
        "id": "task_001",
        "text": "這週試試看，有沒有一個念頭你可以說出來但不跟著它走",
        "detect_keywords": ["念頭", "想法", "我發現", "我注意到"],
        "complete_reply": "✓ 你剛才做到了——說出念頭，但沒有變成它",
    },
    {
        "id": "task_002",
        "text": "這週注意一次你身體的感受，然後告訴我",
        "detect_keywords": ["胸口", "肩膀", "呼吸", "身體", "緊", "沉"],
        "complete_reply": "✓ 你注意到了身體在說什麼",
    },
    {
        "id": "task_003",
        "text": "這週說出一件你一直想說但沒說的事",
        "detect_keywords": ["其實", "一直", "沒說", "想說"],
        "complete_reply": "✓ 說出來了，這需要勇氣",
    },
    {
        "id": "task_004",
        "text": "這週試著描述一個情緒，不用「很」這個字",
        "detect_keywords": [],  # 用戶主動說完成
        "complete_reply": "✓ 找到更精確的詞，這讓情緒更容易被你看見",
    },
    {
        "id": "task_005",
        "text": "找一個你給別人但不給自己的標準",
        "detect_keywords": ["如果是別人", "換成朋友", "標準"],
        "complete_reply": "✓ 你看到了那個雙重標準",
    },
]


def get_current_week_task() -> dict:
    """依當週週次輪替任務（不依用戶，全局同步）"""
    from datetime import datetime
    week_num = datetime.now().isocalendar()[1]
    return WEEKLY_TASKS[week_num % len(WEEKLY_TASKS)]


def get_weekly_task_push_text(task: dict) -> str:
    return (
        f"🎯 本週的邀請\n\n"
        f"{task['text']}\n\n"
        f"不一定要完成，只是試試看。\n"
        f"有的話在對話裡說一下就算 ✓"
    )


def detect_task_completion(
    user_text: str, session: dict
) -> Optional[str]:
    """
    掃描用戶訊息，偵測是否完成本週任務
    已完成則回傳完成訊息，否則 None
    """
    if session.get("task_completed_this_week"):
        return None

    task = get_current_week_task()
    if not task["detect_keywords"]:
        return None

    if any(kw in user_text for kw in task["detect_keywords"]):
        session["task_completed_this_week"] = True
        session["task_completed_id"] = task["id"]
        return task["complete_reply"]

    return None


# ════════════════════════════════════════════════════════
# 3. 對話結尾感
# ════════════════════════════════════════════════════════

CLOSING_PROMPTS = [
    "今天說了不少 🌙\n如果要用一句話記下今天，你會說什麼？\n（不一定要回覆，只是個邀請）",
    "這段聊完了。\n有沒有什麼，是說出來之後感覺不一樣的？",
    "今天到這裡。\n你現在的狀態，跟一開始說話的時候相比，有什麼不同嗎？",
    "說了這麼多，你覺得最重要的那個部分是什麼？",
]


def should_show_closing(session: dict, arousal_level: int) -> bool:
    """判斷是否應附加對話結尾邀請"""
    today = date.today().isoformat()

    # 每天只顯示一次
    if session.get("closing_shown_date") == today:
        return False

    total_turn = session.get("total_turn", 0)

    # 條件 A：每 5 輪
    if total_turn > 0 and total_turn % 5 == 0:
        return True

    # 條件 B：Arousal 從高降回低（前一輪 ≥ 4，這輪 ≤ 2）
    prev_arousal = session.get("prev_arousal", 3)
    if prev_arousal >= 4 and arousal_level <= 2:
        return True

    # 條件 C：晚上 9 點後（台灣時間）
    from datetime import datetime
    import pytz
    try:
        tz = pytz.timezone("Asia/Taipei")
        now = datetime.now(tz)
        if now.hour >= 21:
            return True
    except Exception:
        pass

    return False


def get_closing_prompt(session: dict) -> str:
    session["closing_shown_date"] = date.today().isoformat()
    return random.choice(CLOSING_PROMPTS)


# ════════════════════════════════════════════════════════
# 4. 情緒個性接話（SHORT_REPLIES）
# ════════════════════════════════════════════════════════

SHORT_REPLIES = {
    # 一字回應（規格 P0 原版）
    "好":    "好——\n是真的好，還是那種懶得說的好？",
    "不好":  "聽起來今天有點重。願意說說嗎？",
    "還好":  "還好——\n是真的還行，還是那種懶得說的還行？",
    "還行":  "還行——\n是真的還行，還是那種不想解釋的還行？",
    "累":    "什麼累？\n身體的，還是那種說不清楚的累？",
    "好累":  "好累——\n什麼最累？",
    "煩":    "煩什麼？\n說說看。",
    "很煩":  "什麼讓你很煩？",
    "超煩":  "什麼讓你超煩？",
    "沒事":  "沒事。\n那就先這樣。\n如果之後有什麼，我在。",
    "沒什麼": "沒什麼——\n那個「沒什麼」是真的沒什麼，還是說不知道從哪說起？",
    "不知道": "不知道也是一種答案。\n現在腦袋裡有在轉什麼嗎？哪怕只是一個詞。",
    "算了":  "算了——\n是真的放下了，還是那種撐不住的算了？",
    "隨便":  "隨便——\n是真的無所謂，還是說不知道怎麼選？",
    "無所謂": "無所謂——\n這個感覺是怎麼來的？",
    "無聊":  "無聊的時候，有什麼事情你會想到但沒說的嗎？",
    "沒用":  "說這話的時候，心裡在想什麼？",
    "好難":  "什麼感覺很難？",
    "不想":  "不想做什麼？",
    "討厭":  "討厭什麼？",
    "生氣":  "什麼讓你生氣？",
    "傷心":  "傷心什麼？",
    "害怕":  "在怕什麼呢？",
    "開心":  "今天有什麼讓你開心的事？",
    "謝謝":  "不客氣 🌙\n還有什麼想說的嗎？",
    "嗯":    "嗯——\n然後呢？",
    "哦":    "哦——\n你覺得怎麼樣？",
    "喔":    "喔——\n繼續說？",
    "ok":    "ok——\n真的 ok，還是先這樣說？",
    "OK":    "ok——\n真的 ok，還是先這樣說？",
    "好的":  "好的——\n有沒有什麼還沒說完的？",
    "沒關係": "沒關係——\n那個「沒關係」是真的，還是說給自己聽的？",
    "沒辦法": "沒辦法——\n是什麼讓你覺得沒辦法？",
    "不想說": "可以不說。\n我在，你要說的時候說。",
}

# ════════════════════════════════════════════════════════
# 4b. P1-B 情緒關鍵字個性接話擴充（短句靜態庫）
# ════════════════════════════════════════════════════════

SHORT_PHRASE_REPLIES = {
    # 否定短句
    "沒什麼": "沒什麼——那個「沒什麼」是真的沒什麼，還是說不知道從哪說起？",
    "沒關係": "沒關係——那個「沒關係」是說給別人聽，還是也說給自己聽？",
    "沒事的": "沒事的——是在安慰自己，還是真的過了？",
    # 時間詞短句
    "最近很差": "最近——是累積下來的，還是突然發生了什麼？",
    "最近不好": "最近——是慢慢堆出來的，還是有一件事特別重？",
    "這週很糟": "這週——發生了什麼讓你覺得糟？",
    "最近很累": "最近的累，是哪一種？身體的，還是心裡的，還是都有？",
    # 比較句
    "比上週好一點": "好一點了。那個「一點點」，你是怎麼撐過來的？",
    "比之前好": "比之前好了。這個「好一點」你自己有感覺到嗎？",
    "沒有昨天那麼糟": "沒有昨天那麼糟，算是有一點喘息到？",
    # 原因不明
    "就是不開心": "莫名的——有時候感覺就是先到，原因還在後面。現在身體有什麼感覺嗎？",
    "莫名其妙": "莫名的——有時候感覺就是先到，原因還在後面。現在腦袋在轉什麼？",
    "就是煩": "就是煩——說不清楚的那種？還是有具體的事情？",
    # 自我批評
    "我很廢": "你現在對自己說這個，是因為發生了什麼事？",
    "我好差": "你現在對自己說這個，是因為發生了什麼？",
    "我真的很廢": "說出這句話的時候，腦袋裡在想哪件具體的事？",
    "都是我的問題": "是什麼讓你覺得都是你的問題？",
    # 關係詞
    "跟他吵架": "說說看，怎麼了？",
    "被說了": "被說了什麼？",
    "跟她吵架": "說說看，發生了什麼？",
    # 放棄語氣
    "就這樣吧": "就這樣——是真的想好了，還是先不想了？",
    "算了啦": "算了之前，有沒有什麼還想說的？",
    "無所謂了": "無所謂了——這個感覺是怎麼來的？",
    # 確認語氣
    "對啊": "對啊。說出來之後，感覺有沒有不一樣一點？",
    "就是這樣": "就是這樣。說出來之後，感覺有沒有不一樣一點？",
    "你說對了": "你說對了。說出來了，現在怎麼樣？",
}


def check_short_reply(user_text: str) -> Optional[str]:
    """
    精確匹配短訊息接話
    1. ≤ 4 字 → 精確匹配 SHORT_REPLIES
    2. ≤ 10 字 → 從 SHORT_PHRASE_REPLIES 找包含匹配
    """
    text = user_text.strip()

    # 精確匹配
    if len(text) <= 4:
        result = SHORT_REPLIES.get(text)
        if result:
            return result

    # 短句包含匹配
    if len(text) <= 12:
        for phrase, reply in SHORT_PHRASE_REPLIES.items():
            if phrase in text:
                return reply

    return None


# ════════════════════════════════════════════════════════
# 5. 成長樹系統
# ════════════════════════════════════════════════════════

TREE_STAGES = {
    0: {"emoji": "🌱", "name": "種子",  "threshold": 0},
    1: {"emoji": "🌿", "name": "發芽",  "threshold": 7},
    2: {"emoji": "🌳", "name": "小樹",  "threshold": 21},
    3: {"emoji": "🌸", "name": "開花",  "threshold": 42},
    4: {"emoji": "✨", "name": "結果",  "threshold": 70},
}

TREE_UPGRADE_MSG = {
    1: "🌿 你的種子發芽了\n連續記錄讓它有了第一片葉子",
    2: "🌳 長成小樹了\n你說的那些話，都成了它的養分",
    3: "🌸 開花了\n你有沒有注意到，你說話的方式和剛開始不太一樣了",
    4: "✨ 結果了\n這棵樹是你用一次次的誠實種出來的",
}

TREE_TIPS = [
    "簽到一次就能讓它喝到水",
    "說說話，給它一點陽光",
    "它在等你",
]


def get_tree_stage(water: int) -> int:
    for stage in sorted(TREE_STAGES.keys(), reverse=True):
        if water >= TREE_STAGES[stage]["threshold"]:
            return stage
    return 0


def update_tree(
    session: dict,
    event: str,  # "checkin" | "dialog_5turn" | "new_method"
) -> tuple[dict, Optional[str]]:
    """
    更新成長樹資源，回傳（更新後 session, 升階訊息或 None）
    event:
      "checkin"      → +1 water
      "dialog_5turn" → +1 sun（每 5 輪對話）
      "new_method"   → +1 nutrient（使用非預設方法）
    """
    water    = session.get("tree_water", 0)
    sun      = session.get("tree_sun", 0)
    nutrient = session.get("tree_nutrient", 0)
    old_stage = get_tree_stage(water)

    if event == "checkin":
        water += 1
    elif event == "dialog_5turn":
        sun += 1
    elif event == "new_method":
        nutrient += 1

    new_stage = get_tree_stage(water)
    session["tree_water"]    = water
    session["tree_sun"]      = sun
    session["tree_nutrient"] = nutrient
    session["tree_stage"]    = new_stage

    upgrade_msg = None
    if new_stage > old_stage:
        upgrade_msg = TREE_UPGRADE_MSG.get(new_stage)

    return session, upgrade_msg


def get_tree_status_message(session: dict) -> str:
    water  = session.get("tree_water", 0)
    sun    = session.get("tree_sun", 0)
    stage  = get_tree_stage(water)
    info   = TREE_STAGES[stage]
    tip    = random.choice(TREE_TIPS)
    return (
        f"🌙 你的樹這週的狀態：\n"
        f"{info['emoji']} {info['name']}\n\n"
        f"水分 {water} ・ 陽光 {sun}\n\n"
        f"{tip}"
    )


# ════════════════════════════════════════════════════════
# 6. 情緒詞典解鎖
# ════════════════════════════════════════════════════════

EMOTION_DICT = {
    "rumination": {
        "trigger_keywords": ["一直想", "停不下來", "反覆", "轉"],
        "name": "反芻思考 Rumination",
        "desc": "讓同一個念頭反覆轉的狀態。\n能說出這個詞的人，比較容易和它保持距離。",
        "rarity": "common",
    },
    "defusion": {
        "trigger_keywords": ["念頭", "想法", "我有一個"],
        "name": "認知解融 Defusion",
        "desc": "你和你的念頭之間，其實有空間。\n這個技術叫做解融——看著念頭，但不變成它。",
        "rarity": "uncommon",
    },
    "window_of_tolerance": {
        "trigger_keywords": ["情緒很強", "失控", "崩潰", "還好"],
        "name": "容納之窗 Window of Tolerance",
        "desc": "每個人都有一個情緒可以被處理的範圍。\n你今天在窗裡，還是窗外？",
        "rarity": "uncommon",
    },
    "core_belief": {
        "trigger_keywords": ["我就是", "一直都", "從來都", "本來就"],
        "name": "核心信念 Core Belief",
        "desc": "那些我們深信不疑的句子，\n通常比事實更早到。",
        "rarity": "rare",
    },
    "somatic": {
        "trigger_keywords": ["胸口", "肩膀", "呼吸", "身體", "緊", "沉"],
        "name": "身體感知 Somatic Awareness",
        "desc": "情緒在被說出來之前，\n身體已經知道了。",
        "rarity": "uncommon",
    },
    "insight": {
        "trigger_keywords": ["我發現", "原來", "才發現", "突然"],
        "name": "洞察 Insight",
        "desc": "那個「啊——」的瞬間。\n改變有時候就從這裡開始。",
        "rarity": "rare",
    },
    "alliance_rupture": {
        "trigger_keywords": ["你不懂", "沒用", "算了"],
        "name": "治療同盟破裂 Alliance Rupture",
        "desc": "有時候，說「沒用」的那一刻，\n反而是最接近真實感受的時候。",
        "rarity": "rare",
    },
    "self_compassion": {
        "trigger_keywords": ["對自己", "不夠好", "太嚴格"],
        "name": "自我慈悲 Self-Compassion",
        "desc": "你對朋友說話的方式，\n可以用來對自己說嗎？",
        "rarity": "uncommon",
    },
}

RARITY_TEXT = {
    "common":   "常見洞察",
    "uncommon": "少見發現",
    "rare":     "✨ 稀有時刻",
}


async def scan_emotion_keywords(
    user_text: str, user_id: str, unlocked_words: set[str]
) -> Optional[str]:
    """
    掃描用戶訊息是否觸發詞典解鎖
    unlocked_words: 已解鎖的 word_id 集合（從 DB 讀取）
    回傳解鎖通知文字，或 None
    """
    for word_id, info in EMOTION_DICT.items():
        if word_id in unlocked_words:
            continue
        if any(kw in user_text for kw in info["trigger_keywords"]):
            # 寫入 DB
            try:
                from services.db_persistent import unlock_emotion_word
                await unlock_emotion_word(user_id, word_id)
            except Exception as e:
                print(f"[Nudge] Emotion dict unlock failed: {e}")

            rarity = RARITY_TEXT.get(info["rarity"], "")
            return (
                f"📚 你解鎖了一個詞：\n\n"
                f"［{info['name']}］\n"
                f"{info['desc']}\n\n"
                f"（{rarity}）"
            )
    return None


# ════════════════════════════════════════════════════════
# 7. 天氣描述（依近 7 天平均 Arousal）
# ════════════════════════════════════════════════════════

def get_weather_description(avg_arousal_7d: float, trend: str) -> str:
    """
    avg_arousal_7d: 最近7天平均 Arousal（1-5）
    trend: "up" / "down" / "stable"
    """
    if avg_arousal_7d <= 1.5:
        return "最近感覺有點沉，像陰天 🌫"
    elif avg_arousal_7d <= 2.5 and trend == "down":
        return "最近在慢慢平靜下來，像雨後 🌤"
    elif avg_arousal_7d <= 2.5:
        return "最近狀態還穩，像晴天 ☀️"
    elif avg_arousal_7d <= 3.5:
        return "最近有點起伏，像多雲 ⛅"
    elif avg_arousal_7d <= 4.0:
        return "最近情緒比較強烈，像大風天 🌬"
    else:
        return "最近承受了很多，像暴風雨 🌧"


# ════════════════════════════════════════════════════════
# 8. P1-A 里程碑回饋系統
# ════════════════════════════════════════════════════════

MILESTONE_DAYS = [7, 14, 30]

MILESTONE_TEMPLATES = {
    7: (
        "你已經和我聊了 7 天了 🌱\n\n"
        "這一週裡，你最常說到的是：\n"
        "「{kw1}」「{kw2}」「{kw3}」\n\n"
        "{analysis}\n\n"
        "願意持續面對這些，\n這本身就是一件事。"
    ),
    14: (
        "14 天了 🌿\n\n"
        "兩週前的你和現在的你，\n說話的方式有一點點不一樣了。\n\n"
        "這段時間最常出現的主題：\n"
        "「{kw1}」「{kw2}」「{kw3}」\n\n"
        "{analysis}\n\n"
        "你一直在。"
    ),
    30: (
        "一個月 🌙\n\n"
        "你在這裡說過很多事情。\n"
        "有些說出來就輕了，\n有些說了還是很重，但你沒有停下來。\n\n"
        "這個月你最常回到的地方：\n"
        "「{kw1}」「{kw2}」「{kw3}」\n\n"
        "{analysis}\n\n"
        "謝謝你願意在這裡。"
    ),
}

MILESTONE_ANALYSIS_PROMPT = """你是心事日記。以下是用戶這段時間的高頻關鍵詞：
{keywords}

請生成一句（7/14天）或兩句（30天）
能讓用戶感覺「被看見」的觀察。

規則：
- 不評價好壞
- 不給建議
- 說的是用戶在做的事，不是用戶應該做的事
- 語氣像一個陪伴者在說「我注意到你」
- 只輸出觀察文字，不要其他格式"""


async def generate_milestone_analysis(keywords: list[str], days: int) -> str:
    """AI 生成里程碑分析文字"""
    from services.llm import call_api
    kw_str = "、".join(keywords) if keywords else "（暫無足夠資料）"
    sentences = "一句話" if days < 30 else "兩句話"
    prompt = (
        f"以下是用戶最常說到的詞：{kw_str}\n\n"
        f"請生成{sentences}，讓用戶感覺「被看見」。\n"
        f"只輸出觀察文字。"
    )
    try:
        result = await call_api(
            prompt=prompt,
            system=MILESTONE_ANALYSIS_PROMPT.format(keywords=kw_str),
            max_tokens=100,
        )
        return result.strip() if result else ""
    except Exception:
        return ""


async def check_milestone(user_id: str) -> Optional[str]:
    """
    檢查用戶是否達到里程碑，達到則回傳里程碑訊息，否則 None
    應在對話結尾後呼叫
    """
    try:
        from services.db_persistent import (
            count_conversation_days, check_and_mark_milestone, get_top_keywords
        )
        days = await count_conversation_days(user_id)

        for milestone in MILESTONE_DAYS:
            if days >= milestone:
                # 先生成觀察文字，再儲存（首次儲存才算觸發）
                keywords = await get_top_keywords(user_id, limit=5)
                analysis = await generate_milestone_analysis(keywords, milestone)
                # 里程碑塔羅（大阿爾克那成長牌池）
                tarot_card = tarot_meaning = None
                tarot_reversed = False
                try:
                    from services.symbolic import assign_milestone_tarot
                    tarot = assign_milestone_tarot()
                    tarot_card    = tarot["card_name"]
                    tarot_meaning = tarot["meaning"]
                    tarot_reversed = tarot["is_reversed"]
                except Exception:
                    pass
                is_first = await check_and_mark_milestone(
                    user_id, milestone, observation=analysis,
                    tarot_card=tarot_card,
                    tarot_meaning=tarot_meaning,
                    tarot_reversed=tarot_reversed,
                )
                if is_first:
                    kws = keywords + ["…"] * 3
                    template = MILESTONE_TEMPLATES[milestone]
                    msg = template.format(
                        kw1=kws[0], kw2=kws[1], kw3=kws[2],
                        analysis=analysis,
                    )
                    return msg
    except Exception as e:
        print(f"[Milestone] Error: {e}")
    return None


# ════════════════════════════════════════════════════════
# 9. P2-A 簽到情緒月曆 emoji 推斷
# ════════════════════════════════════════════════════════

EMOTION_EMOJI_MAP = {
    "ACUTE_DISTRESS": "😔",
    "RUMINATION":     "😟",
    "SELF_BLAME":     "😟",
    "CONFUSION":      "😐",
    "CALM_REFLECTIVE":"😌",
    "ANGER":          "😤",
    "ANXIETY":        "😟",
    "SAD":            "😔",
    "HAPPY":          "😊",
    "RELIEF":         "😌",
    "NEUTRAL":        "😐",
}

EMOTION_EMOJI_PROMPT = """根據以下今日對話內容，推斷用戶今天的整體情緒狀態。

對話內容：{today_conversation}

從以下選擇一個最接近的情緒 emoji：
😔 悲傷／沉重
😟 焦慮／擔憂
😤 憤怒／煩躁
😐 平淡／無感
😌 平靜／還好
🙂 輕鬆／小確幸
😊 愉快／滿足

只輸出一個 emoji，不輸出其他內容。"""

VALID_EMOJIS = {"😔", "😟", "😤", "😐", "😌", "🙂", "😊"}


async def infer_emotion_emoji(today_messages: list[str], checkin_emotion: str = "") -> tuple[str, str]:
    """
    從今日對話推斷情緒 emoji
    返回 (emoji, label)
    """
    # 先嘗試從簽到 emotion 映射
    if checkin_emotion in EMOTION_EMOJI_MAP:
        emoji = EMOTION_EMOJI_MAP[checkin_emotion]
        return emoji, checkin_emotion

    # 無對話則返回預設
    if not today_messages:
        return "😐", "NEUTRAL"

    # AI 推斷
    try:
        from services.llm import call_api
        conversation_text = "\n".join(today_messages[-20:])
        result = await call_api(
            prompt="請推斷情緒 emoji。",
            system=EMOTION_EMOJI_PROMPT.format(today_conversation=conversation_text),
            max_tokens=5,
        )
        if result:
            result = result.strip()
            for emoji in VALID_EMOJIS:
                if emoji in result:
                    return emoji, result
    except Exception:
        pass

    return "😐", "NEUTRAL"


async def save_checkin_emotion(user_id: str, emoji: str, label: str) -> None:
    """儲存今日簽到情緒到月曆"""
    try:
        from datetime import date
        from services.db_persistent import save_emotion_calendar
        await save_emotion_calendar(user_id, date.today(), emoji, label)
    except Exception as e:
        print(f"[EmotionCalendar] save failed: {e}")


def format_checkin_response(streak: int, emoji: str) -> str:
    """生成簽到回應訊息"""
    if streak == 0 or streak == 1:
        return f"簽到成功 🌙\n今天是你記錄的第 {max(1, streak)} 天。"
    elif streak < 7:
        return f"簽到成功 🌙\n今天是你連續記錄的第 {streak} 天。"
    elif streak == 7:
        return (
            f"🌿 你已經連續記錄 7 天了\n\n"
            f"堅持到第 7 天，\n這不是小事。"
        )
    elif streak == 14:
        return (
            f"🌿 連續 14 天 ✓\n\n"
            f"兩週的你，和第一天不一樣了。"
        )
    elif streak == 30:
        return (
            f"💎 30 天了\n\n"
            f"一個月前你開始記錄，\n今天你還在。\n這就是答案。"
        )
    else:
        return f"簽到成功 🔥\n連續 {streak} 天了。"
