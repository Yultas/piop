"""Minimal client for OpenAI-compatible chat completion APIs."""
import httpx
from fastapi import HTTPException
from backend.app.models import AISettings

REQUEST_TIMEOUT = 120.0


def _headers(cfg: AISettings) -> dict:
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    return headers


def _base(cfg: AISettings) -> str:
    return cfg.base_url.rstrip("/")


def _provider_error(res: httpx.Response) -> HTTPException:
    try:
        body = res.json()
        message = body.get("error", {}).get("message") or str(body)
    except ValueError:
        message = res.text[:300]
    return HTTPException(status_code=502, detail=f"AI provider error ({res.status_code}): {message}")


async def chat_completion(cfg: AISettings, messages: list[dict], tools: list[dict]) -> dict:
    """Return the assistant message dict ({content, tool_calls}) of the first choice."""
    payload = {"model": cfg.model, "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            res = await client.post(f"{_base(cfg)}/chat/completions", json=payload, headers=_headers(cfg))
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"AI provider unreachable: {exc}") from exc
    if res.status_code >= 400:
        raise _provider_error(res)
    choices = res.json().get("choices") or []
    if not choices:
        raise HTTPException(status_code=502, detail="AI provider returned no choices")
    return choices[0].get("message") or {}


async def list_models(cfg: AISettings) -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.get(f"{_base(cfg)}/models", headers=_headers(cfg))
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"AI provider unreachable: {exc}") from exc
    if res.status_code >= 400:
        raise _provider_error(res)
    return sorted(m.get("id", "") for m in res.json().get("data", []) if m.get("id"))
