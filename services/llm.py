"""
統一 LLM 呼叫層
自動偵測：有 GROQ_API_KEY → 用 Groq（免費，500k tokens/day）
          有 ANTHROPIC_API_KEY → 用 Anthropic Claude
          兩者都有 → Groq 優先
"""
import os
import httpx

# ── 模型對應 ─────────────────────────────────────────────
_MODELS = {
    "groq": {
        "sonnet": "llama-3.3-70b-versatile",   # 主力對話
        "haiku":  "llama-3.1-8b-instant",        # 輕量診斷 / 快速判斷
    },
    "anthropic": {
        "sonnet": "claude-sonnet-4-6",
        "haiku":  "claude-haiku-4-5-20251001",
    },
}


def _provider() -> str:
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    return "anthropic"


async def call_api(
    prompt: str,
    max_tokens: int = 300,
    tier: str = "sonnet",
    system: str = "",
) -> str:
    """
    統一入口
    tier: "sonnet"（主力）或 "haiku"（診斷/快速判斷，更便宜）
    system: 可選 system prompt（Anthropic 支援，Groq 走第一則 messages）
    回傳純文字，失敗回傳空字串
    """
    provider = _provider()
    model = _MODELS[provider][tier]

    messages = []
    if system and provider == "groq":
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        if provider == "groq":
            return await _call_groq(model, messages, max_tokens)
        else:
            return await _call_anthropic(model, messages, max_tokens, system)
    except Exception as e:
        print(f"[LLM {provider} Error] {e}")
        return ""


async def _call_groq(model: str, messages: list, max_tokens: int) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {os.environ.get('GROQ_API_KEY', '')}",
            },
            json={"model": model, "max_tokens": max_tokens, "messages": messages},
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


async def _call_anthropic(
    model: str, messages: list, max_tokens: int, system: str
) -> str:
    payload: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        payload["system"] = system

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
                "anthropic-version": "2023-06-01",
            },
            json=payload,
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"].strip()
