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
        for h in history[-6:]  # 只取最近 6 輪
    ])

    prompt = f"""你是受過訓練的心理健康對話評估系統。
根據以下對話，評估用戶當前狀態。只回傳 JSON，不要其他文字。

對話記錄（最近幾輪）：
{history_text}

用戶最新訊息：「{user_text}」

回傳格式：
{{
  "arousal_level": 1到5的整數,
  "defense_mechanism": "INTELLECTUALIZATION|EXTERNALIZATION|NONE",
  "alliance_rupture": "CONFRONTATION|WITHDRAWAL|NONE",
  "notes": "簡短說明評估依據"
}}

評估標準：
- arousal_level 1：過低喚起（解離、麻木、沒感覺）
- arousal_level 2-3：容納之窗內（能溝通、有情緒但穩定）
- arousal_level 4：臨界過度喚起（情緒強烈、難以思考）
- arousal_level 5：全面崩潰（恐慌、解離、危機狀態）

- INTELLECTUALIZATION：用道理/分析逃避情緒（「我知道這是認知扭曲但我就是...」）
- EXTERNALIZATION：把問題全歸因於他人（「都是因為他/她/他們」）
- CONFRONTATION：直接挑戰Bot（「你不懂我」「這問題很蠢」）
- WITHDRAWAL：沉默、很短的回覆、失去投入感"""

    try:
        raw = await call_api(prompt, max_tokens=300, tier="haiku")
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
