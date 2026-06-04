"""
P1 臨床診斷器
評估 Arousal Level、防衛機制、治療同盟破裂
"""

import json
from dataclasses import dataclass
from typing import Optional, Literal
from services.llm import call_api


ArousaLevel = Literal[1, 2, 3, 4, 5]
DefenseMechanism = Literal["INTELLECTUALIZATION", "EXTERNALIZATION", "NONE"]
AllianceRupture = Literal["CONFRONTATION", "WITHDRAWAL", "NONE"]


@dataclass
class DiagnosisResult:
    arousal_level: int = 3          # 1-5，容納之窗
    defense_mechanism: str = "NONE"  # INTELLECTUALIZATION / EXTERNALIZATION / NONE
    alliance_rupture: str = "NONE"  # CONFRONTATION / WITHDRAWAL / NONE
    referral_probability: float = 0.3
    notes: str = ""

    @property
    def is_crisis(self) -> bool:
        return self.arousal_level == 5

    @property
    def should_pause_method(self) -> bool:
        """是否應暫停方法推進（修復治療同盟）"""
        return self.alliance_rupture != "NONE" or self.arousal_level >= 4

    def forbidden_methods(self) -> list[str]:
        """依防衛機制禁用的方法"""
        forbidden = []
        if self.defense_mechanism == "EXTERNALIZATION":
            forbidden.append("BYRON_KATIE")
        if self.defense_mechanism == "INTELLECTUALIZATION":
            forbidden.append("METACOGNITION")
        if self.arousal_level == 5:
            forbidden.extend(["BYRON_KATIE", "METACOGNITION", "SOCRATIC", "SQT"])
        return forbidden

    def referral_message(self) -> Optional[str]:
        """依 Arousal 給出轉介訊息"""
        if self.arousal_level == 5:
            return "我很擔心你現在的狀態。安心專線 1925，24小時都有人接。"
        if self.arousal_level == 4:
            return "你現在承受的很沉重，如果可以的話，跟專業諮商師談談會很有幫助。"
        return None


_DIAGNOSE_SYSTEM = """# Role
你是一位資深的臨床心理諮商師與文本分析專家。你的任務是分析用戶最新的一則訊息，並嚴格依據以下心理學指標進行客觀評估，輸出 JSON 格式。只輸出 JSON，不要任何前言或解釋。

# Evaluation Metric Guidelines

1. Arousal Level（情緒喚起強度：1-5）：
   - 1（極低）：情感平淡、麻木、抽離、機械式回應。
   - 2（低）：輕微情感波動，能平靜敘述，基本不帶張力。
   - 3（中等）：正常的情緒表達，有起伏但可控，在容納之窗內。
   - 4（高）：情緒強烈、思考受干擾，接近容納之窗邊緣。
   - 5（極高）：情緒極度激昂、恐慌、狂喜、極度憤怒或崩潰邊緣。

2. Defense Mechanism（防衛機制識別）：
   - INTELLECTUALIZATION（理智化）：邏輯過度清晰，用冰冷的專有名詞、大道理分析自己的痛苦，迴避真實情感。例：「這只是我多巴胺分泌失調的客觀現象」。
   - EXTERNALIZATION（外在化）：將所有痛苦與衝突歸咎於環境、他人或運氣，自身毫無反思。例：「都是這破公司和垃圾主管害的」。
   - NONE：坦然面對、直接表達核心脆弱或感受，或明顯有以上兩種混合使用。

3. Alliance Rupture（同盟破裂偵測）：
   - CONFRONTATION（對抗）：用戶對 AI 的回應表示不滿、反駁、諷刺或攻擊。例：「你根本不懂」、「少跟我講這種機器人話」。
   - WITHDRAWAL（抽離）：用戶受到傷害或感到失望後，開始敷衍、拒絕深入對話。例：「算了」、「隨便，你說是就是吧」。
   - NONE：互動良好，願意信任並深化對話。

# Output Format（JSON Only）
{
  "arousal_level": 1到5的整數,
  "defense_mechanism": "INTELLECTUALIZATION" | "EXTERNALIZATION" | "NONE",
  "alliance_rupture": "CONFRONTATION" | "WITHDRAWAL" | "NONE",
  "notes": "簡短說明評估依據（20字以內）"
}"""


async def diagnose(
    user_text: str,
    history: list[dict],
    session_turn: int = 0
) -> DiagnosisResult:
    """
    呼叫 Claude API 進行臨床評估
    回傳 DiagnosisResult
    """

    history_text = "\n".join([
        f"{'用戶' if h['role'] == 'user' else 'Bot'}: {h['text']}"
        for h in history[-6:]
    ])

    prompt = f"""對話記錄（最近幾輪）：
{history_text}

用戶最新訊息：「{user_text}」

請依評估標準輸出 JSON。"""

    try:
        raw = await call_api(
            prompt,
            system=_DIAGNOSE_SYSTEM,
            max_tokens=200,
            tier="haiku",
        )
        raw = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)
        arousal = int(parsed.get("arousal_level", 3))
        referral_prob = {1: 0.1, 2: 0.3, 3: 0.3, 4: 0.6, 5: 1.0}.get(arousal, 0.3)
        return DiagnosisResult(
            arousal_level=arousal,
            defense_mechanism=parsed.get("defense_mechanism", "NONE"),
            alliance_rupture=parsed.get("alliance_rupture", "NONE"),
            referral_probability=referral_prob,
            notes=parsed.get("notes", "")
        )
    except Exception as e:
        print(f"[Clinical Diagnosis Error] {e}")
        return DiagnosisResult()  # 預設安全值


def get_rupture_repair_response(rupture_type: str) -> str:
    """治療同盟破裂修復語句"""
    if rupture_type == "CONFRONTATION":
        return (
            "你說的對，我可能沒有真的懂你說的。\n"
            "你願意再說一次，讓我試著更靠近你的感受嗎？"
        )
    if rupture_type == "WITHDRAWAL":
        return "沒關係，不一定要說什麼。我在這裡。"
    return ""
