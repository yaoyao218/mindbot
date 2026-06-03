"""
tarot_quotes_pool.py — 投射塔羅牌庫 + 哲人名言庫

TAROT_POOL  : 投射牌（STAGNANT 路徑用）
              每張牌含 name_zh / desc（畫面描述）/ question（fallback 問句）/ dimensions
QUOTE_POOL  : 情緒標籤 → 哲人名言列表（每則含 text + author）
              key 使用中文情緒標籤，與 session_psych.emotion 一致
"""

import random

# ══════════════════════════════════════════════════════════
# 1. 投射塔羅牌庫
# ══════════════════════════════════════════════════════════

TAROT_POOL: dict[str, dict] = {
    "SWORDS_2": {
        "name_zh": "寶劍二・正位",
        "desc": "畫面中一個人被蒙上雙眼，雙手握劍交叉在胸前，背對著洶湧的大海。",
        "question": (
            "這個『還好』，會不會是你在努力把某些煩人的事情擋在外面？"
            "你覺得背後那片海最像你最近不想面對的哪件事？"
        ),
        "dimensions": ["cognition", "defense"],
    },
    "CUPS_4": {
        "name_zh": "聖杯四・正位",
        "desc": "一隻手從雲端遞出一個新杯子，但樹下的人雙手抱胸、別過頭去，看都不想看。",
        "question": (
            "你現在的心情是不是也覺得『反正別人說什麼都沒用、算了』？"
            "那個讓你無力的『算了』到底是什麼？"
        ),
        "dimensions": ["emotion", "withdrawal"],
    },
    "SWORDS_9": {
        "name_zh": "寶劍九・正位",
        "desc": "深夜裡，一個人從夢中驚醒，雙手遮住臉，九把劍懸在黑暗的牆壁上。",
        "question": (
            "那些在深夜才出現的擔心，現在有沒有在你心裡轉？"
            "最重的那一個念頭是什麼？"
        ),
        "dimensions": ["anxiety", "rumination"],
    },
    "MOON": {
        "name_zh": "月亮・正位",
        "desc": "月光下，一條路通向遠方，兩側有狼與狗在嚎叫，路的盡頭是霧茫茫的城門。",
        "question": (
            "你現在有沒有一種『不確定自己走的路對不對』的感覺？"
            "那個讓你感到模糊不安的地方是什麼？"
        ),
        "dimensions": ["confusion", "self_doubt"],
    },
    "PENTS_4": {
        "name_zh": "錢幣四・正位",
        "desc": "一個人緊緊抱著四枚金幣，腳踩兩枚，頭頂一枚，眼神警戒地望向前方。",
        "question": (
            "你現在是不是有點想把所有能量都守住、不想再多給出去了？"
            "那個讓你覺得必須緊抱不放的，是什麼？"
        ),
        "dimensions": ["exhaustion", "control"],
    },
    "HERMIT": {
        "name_zh": "隱士・正位",
        "desc": "一個老者獨自站在山頂，手持燈籠，燈光照亮的範圍只有腳邊一小圈。",
        "question": (
            "你現在有沒有想一個人待著、不想解釋任何事的感覺？"
            "那個想獨處的背後，藏著什麼？"
        ),
        "dimensions": ["isolation", "exhaustion"],
    },
    "TOWER": {
        "name_zh": "塔・正位",
        "desc": "一座高塔被閃電擊中，塔頂的王冠飛走，人們從塔上跌落。",
        "question": (
            "最近有什麼事讓你覺得『完了，一切都不一樣了』？"
            "那個突然崩塌的感覺最像生活裡的哪一塊？"
        ),
        "dimensions": ["crisis", "anger"],
    },
    "STAR": {
        "name_zh": "星星・正位",
        "desc": "夜空中，一位女子跪在水邊，把水倒入湖中又倒上地面，八顆星在她頭頂閃爍。",
        "question": (
            "就算現在很累，你心裡有沒有一點點覺得『也許之後會好一點』的感覺？"
            "那個小小的希望是什麼？"
        ),
        "dimensions": ["hope", "calm"],
    },
}

# 情緒 → 投射牌 key 列表（按優先序排列）
_EMOTION_TO_CARDS: dict[str, list[str]] = {
    "焦慮":    ["SWORDS_9", "SWORDS_2"],
    "憤怒":    ["TOWER",    "SWORDS_2"],
    "悲傷":    ["CUPS_4",   "MOON"],
    "委屈":    ["CUPS_4",   "SWORDS_2"],
    "疲憊":    ["PENTS_4",  "HERMIT"],
    "自我懷疑": ["MOON",    "SWORDS_9"],
    "複雜混合": ["MOON",    "SWORDS_2"],
    "迷茫":    ["HERMIT",   "MOON"],
    "空洞":    ["HERMIT",   "PENTS_4"],
    "平靜":    ["STAR",     "HERMIT"],
    "釋然":    ["STAR",     "CUPS_4"],
}


def pick_projective_card(emotion: str, dimension: str = "emotion") -> str:
    """
    依情緒和心理向度挑選投射牌。
    dimension="cognition"/"defense" 時優先選認知防禦型牌（SWORDS_2）。
    回傳 TAROT_POOL key。
    """
    candidates = _EMOTION_TO_CARDS.get(emotion, [])

    if dimension in ("cognition", "defense"):
        for key in candidates:
            if any(d in ("cognition", "defense") for d in TAROT_POOL[key]["dimensions"]):
                return key

    if candidates:
        return random.choice(candidates)

    return random.choice(list(TAROT_POOL.keys()))


def pool_key_to_card_dict(key: str) -> dict:
    """
    把 TAROT_POOL key 轉成 tarot_projective 模組用的 card dict，
    讓 build_revealed_card_flex / get_projective_question 可以直接使用。
    """
    entry = TAROT_POOL.get(key, {})
    return {
        "card_name":  entry.get("name_zh", key),
        "card_full":  entry.get("name_zh", key),
        "meaning":    entry.get("desc", ""),
        "question":   entry.get("question", ""),
        "is_reversed": False,
        "mode":       "major",
        "pool_key":   key,
    }


# ══════════════════════════════════════════════════════════
# 2. 哲人名言庫
# ══════════════════════════════════════════════════════════

QUOTE_POOL: dict[str, list[dict]] = {
    "焦慮": [
        {"text": "每個人身上都有裂縫，那是光照進來的地方。",       "author": "倫納德・科恩"},
        {"text": "焦慮是自由的眩暈。",                           "author": "齊克果"},
        {"text": "你不需要控制你的想法，只需要停止讓它們控制你。", "author": "丹・米爾曼"},
    ],
    "憤怒": [
        {"text": "憤怒如同抓著一塊燒紅的炭想丟向別人，最先燙傷的是自己。", "author": "佛陀"},
        {"text": "當你憤怒時，先數到十再說話；若仍然憤怒，就數到一百。",   "author": "湯馬斯・傑佛遜"},
        {"text": "你的憤怒是有道理的——它在保護你在乎的東西。",            "author": "哈里特・勒納"},
    ],
    "悲傷": [
        {"text": "悲傷是愛的代價，也是愛曾存在過的證明。",     "author": "C.S.路易斯"},
        {"text": "不要壓抑眼淚，它能讓你的心靈得到慰藉。",     "author": "伏爾泰"},
        {"text": "你的傷痛是聖地的破碎之處，讓光能進入你。",   "author": "魯米"},
    ],
    "委屈": [
        {"text": "你值得被好好對待——不只是偶爾，而是每一天。", "author": "布芮尼・布朗"},
        {"text": "說不出口的委屈最重，但它不需要解釋，只需要被感受。", "author": "馬雅・安傑洛"},
        {"text": "你的需求不是麻煩，你的感受不是矯情。",               "author": "佚名"},
    ],
    "疲憊": [
        {"text": "休息不是放棄，而是重新充電。",         "author": "蓋伊・芬利"},
        {"text": "照顧好自己，不是自私，而是自我保護。", "author": "奧黛麗・洛德"},
        {"text": "你已經用盡全力了，今天就到這裡。",     "author": "佚名"},
    ],
    "自我懷疑": [
        {"text": "你比你想像的更勇敢，比你看起來更強大，比你認為的更聰明。", "author": "A.A.米恩"},
        {"text": "不要用他人的眼光來定義你自己。",                         "author": "卡爾・榮格"},
        {"text": "你正在成為你本來就是的人，這需要時間。",                  "author": "佚名"},
    ],
    "複雜混合": [
        {"text": "感受很複雜不等於你有問題，你只是一個完整的人。", "author": "布芮尼・布朗"},
        {"text": "矛盾是人類最真實的狀態。",                     "author": "費奧多爾・杜斯妥也夫斯基"},
        {"text": "你不需要搞清楚一切，才能繼續走下去。",          "author": "佚名"},
    ],
    "迷茫": [
        {"text": "並非所有迷失的人都是在流浪。",     "author": "J.R.R.托爾金"},
        {"text": "迷茫的時候，你其實還在路上。",     "author": "佚名"},
        {"text": "不知道下一步，不等於走錯了路。",   "author": "佚名"},
    ],
    "空洞": [
        {"text": "空虛感有時是改變的前奏，而不是終點。",   "author": "卡爾・榮格"},
        {"text": "在什麼都感受不到的時候，身體只是在保護你。", "author": "佩特・沃克"},
        {"text": "即使感受不到，你仍然存在，仍然重要。",       "author": "佚名"},
    ],
    "平靜": [
        {"text": "平靜不是缺乏風暴，而是風暴中的靜定。", "author": "佚名"},
        {"text": "你已經足夠了，就是現在這個樣子。",     "author": "卡爾・羅傑斯"},
    ],
    "釋然": [
        {"text": "放下不是放棄，而是接受。",         "author": "佚名"},
        {"text": "某些結束，是更好的開始的空間。",   "author": "魯米"},
        {"text": "學會讓事情流過，是一種很深的勇氣。", "author": "老子"},
    ],
    "default": [
        {"text": "我們不能選擇發生在自己身上的事，但可以選擇如何回應它。", "author": "維克多・弗蘭克"},
        {"text": "你已經走到這裡了，這本身就是勇氣。",                     "author": "佚名"},
        {"text": "今天的你，已經盡力了。",                                 "author": "佚名"},
    ],
}


def fetch_quote_by_emotion(emotion: str) -> dict:
    """
    依情緒取一句哲人名言。
    回傳 {"text": "...", "author": "..."}
    """
    pool = QUOTE_POOL.get(emotion, QUOTE_POOL["default"])
    return random.choice(pool)
