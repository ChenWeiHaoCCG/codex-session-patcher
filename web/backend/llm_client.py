from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from .llm_response import extract_chat_completion_content


CHAT_COMPLETIONS = "chat_completions"
RESPONSES = "responses"
RESPONSE_PARSE_RETRY_ERRORS = (
    "AI 接口返回格式异常：缺少 choices 或 output",
    "AI 接口返回格式异常：choices 为空",
)


def _normalize_responses_content(content: Any) -> list[dict[str, str]]:
    if isinstance(content, str):
        text = content.strip()
        return [{"type": "input_text", "text": text}] if text else []

    if isinstance(content, list):
        parts: list[dict[str, str]] = []
        for item in content:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    parts.append({"type": "input_text", "text": text})
                continue

            if not isinstance(item, dict):
                continue

            text_value = item.get("text")
            if isinstance(text_value, dict):
                text_value = text_value.get("value")
            if not isinstance(text_value, str) or not text_value.strip():
                text_value = item.get("input_text") if isinstance(item.get("input_text"), str) else ""

            if text_value.strip():
                parts.append({"type": "input_text", "text": text_value.strip()})

        return parts

    if content is None:
        return []

    return [{"type": "input_text", "text": json.dumps(content, ensure_ascii=False)}]


def _to_responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue

        role = message.get("role")
        if not isinstance(role, str) or not role.strip():
            role = "user"

        if role.strip() == "system":
            continue

        content = _normalize_responses_content(message.get("content"))
        if not content:
            continue

        normalized.append(
            {
                "role": role.strip(),
                "content": content,
            }
        )

    return normalized


def _extract_responses_instructions(messages: list[dict[str, Any]]) -> str | None:
    instruction_parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue

        role = message.get("role")
        if not isinstance(role, str) or role.strip() != "system":
            continue

        for item in _normalize_responses_content(message.get("content")):
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                instruction_parts.append(text.strip())

    if not instruction_parts:
        return None

    return "\n\n".join(instruction_parts)


def resolve_ai_endpoint(ai_endpoint: str) -> tuple[str, str]:
    endpoint = ai_endpoint.rstrip("/")
    endpoint_lower = endpoint.lower()

    if endpoint_lower.endswith("/responses"):
        return RESPONSES, endpoint
    if endpoint_lower.endswith("/chat/completions"):
        return CHAT_COMPLETIONS, endpoint

    return CHAT_COMPLETIONS, f"{endpoint}/chat/completions"


def build_ai_request(
    ai_endpoint: str,
    ai_model: str,
    messages: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    endpoint_type, endpoint = resolve_ai_endpoint(ai_endpoint)

    if endpoint_type == RESPONSES:
        instructions = _extract_responses_instructions(messages)
        body = {
            "model": ai_model,
            "input": _to_responses_input(messages),
            "max_output_tokens": 1024,
            "temperature": 0.7,
        }
        if instructions:
            body["instructions"] = instructions
        return endpoint, body

    body = {
        "model": ai_model,
        "messages": messages,
        "max_tokens": 1024,
        "temperature": 0.7,
    }
    return endpoint, body


async def request_ai_text(
    ai_endpoint: str,
    ai_key: str,
    ai_model: str,
    messages: list[dict[str, Any]],
) -> str:
    endpoint_type, endpoint = resolve_ai_endpoint(ai_endpoint)
    _, body = build_ai_request(ai_endpoint, ai_model, messages)

    headers = {
        "Content-Type": "application/json",
    }
    if ai_key:
        headers["Authorization"] = f"Bearer {ai_key}"

    timeout = httpx.Timeout(60.0, connect=15.0)
    max_attempts = 3 if endpoint_type == RESPONSES else 1
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(endpoint, json=body, headers=headers)
            return extract_chat_completion_content(resp)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
        except RuntimeError as exc:
            last_error = exc
            if (
                endpoint_type != RESPONSES
                or attempt >= max_attempts
                or not any(msg in str(exc) for msg in RESPONSE_PARSE_RETRY_ERRORS)
            ):
                raise
        await asyncio.sleep(0.6 * attempt)

    if isinstance(last_error, httpx.TimeoutException):
        raise RuntimeError("AI 请求超时，请稍后重试") from last_error
    if isinstance(last_error, httpx.TransportError):
        raise RuntimeError(f"AI 网络请求失败：{last_error}") from last_error
    if last_error is not None:
        raise last_error
    raise RuntimeError("AI 请求失败：未知错误")
