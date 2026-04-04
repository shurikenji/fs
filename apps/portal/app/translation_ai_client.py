"""HTTP transport helpers for AI-backed translation flows."""
from __future__ import annotations

import aiohttp

_AI_TIMEOUT = aiohttp.ClientTimeout(total=45)


def resolve_openai_endpoint(base_url: str, *, compatible_only: bool) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        return "https://api.openai.com/v1/chat/completions"
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    if compatible_only:
        return f"{normalized}/v1/chat/completions"
    return f"{normalized}/v1/chat/completions"


async def request_ai_completion(
    provider: str,
    system_prompt: str,
    user_prompt: str,
    *,
    api_key: str,
    model: str,
    base_url: str = "",
    compatible_only: bool = False,
) -> str:
    provider_value = (provider or "openai").strip().lower()
    if provider_value == "anthropic":
        return await call_anthropic(
            system_prompt,
            user_prompt,
            api_key=api_key,
            model=model,
        )
    if provider_value == "gemini":
        return await call_gemini(
            system_prompt,
            user_prompt,
            api_key=api_key,
            model=model,
        )
    endpoint = resolve_openai_endpoint(base_url, compatible_only=compatible_only)
    return await call_openai_chat(
        system_prompt,
        user_prompt,
        api_key=api_key,
        model=model,
        endpoint=endpoint,
    )


async def call_openai_chat(
    system_prompt: str,
    user_prompt: str,
    *,
    api_key: str,
    model: str,
    endpoint: str,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    async with aiohttp.ClientSession(timeout=_AI_TIMEOUT) as session:
        async with session.post(endpoint, json=payload, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"OpenAI-compatible AI error {resp.status}: {text[:300]}")
            data = await resp.json()
            return (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )


async def call_anthropic(
    system_prompt: str,
    user_prompt: str,
    *,
    api_key: str,
    model: str,
) -> str:
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": model,
        "max_tokens": 1500,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    async with aiohttp.ClientSession(timeout=_AI_TIMEOUT) as session:
        async with session.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Anthropic AI error {resp.status}: {text[:300]}")
            data = await resp.json()
            parts = data.get("content", [])
            if not parts:
                return ""
            return str(parts[0].get("text") or "")


async def call_gemini(
    system_prompt: str,
    user_prompt: str,
    *,
    api_key: str,
    model: str,
) -> str:
    gemini_model = model if model.startswith("gemini-") else f"gemini-{model}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}],
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 1500,
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={api_key}"

    async with aiohttp.ClientSession(timeout=_AI_TIMEOUT) as session:
        async with session.post(url, json=payload, headers={"Content-Type": "application/json"}) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Gemini AI error {resp.status}: {text[:300]}")
            data = await resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return ""
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                return ""
            return str(parts[0].get("text") or "")
