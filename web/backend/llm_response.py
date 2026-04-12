from __future__ import annotations

import json
from typing import Any

import httpx


def _compact_preview(text: str, limit: int = 200) -> str:
    preview = " ".join(text.split())
    if len(preview) <= limit:
        return preview
    return preview[:limit] + "..."


def _extract_error_detail(data: Any) -> str | None:
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
        if isinstance(error, dict):
            for key in ("message", "detail", "type", "code"):
                value = error.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        detail = data.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()

    return None


def _parse_response_json(resp: httpx.Response) -> Any:
    text = resp.text or ""
    if not text.strip():
        raise RuntimeError("AI 接口返回空响应，请检查 API Endpoint 是否正确，或上游服务当前不可用")

    try:
        return resp.json()
    except (json.JSONDecodeError, ValueError):
        preview = _compact_preview(text)
        content_type = resp.headers.get("content-type", "").lower()
        if (
            "html" in content_type
            or preview.lower().startswith("<!doctype html")
            or preview.lower().startswith("<html")
        ):
            raise RuntimeError(
                "AI 接口返回了 HTML 而不是 JSON，请检查 API Endpoint 是否填写为兼容 OpenAI 的 /v1/chat/completions 或 /v1/responses 地址"
            )
        raise RuntimeError(f"AI 接口返回的不是合法 JSON：{preview or '空内容'}")


def _join_text_parts(parts: list[str]) -> str | None:
    cleaned = [part.strip() for part in parts if isinstance(part, str) and part.strip()]
    if not cleaned:
        return None
    return "\n".join(cleaned)


def _extract_text_parts(node: Any, *, allow_reasoning: bool, depth: int = 0) -> list[str]:
    if depth > 8:
        return []

    if isinstance(node, str):
        return [node] if node.strip() else []

    if isinstance(node, list):
        parts: list[str] = []
        for item in node:
            parts.extend(_extract_text_parts(item, allow_reasoning=allow_reasoning, depth=depth + 1))
        return parts

    if not isinstance(node, dict):
        return []

    direct_text_keys = ("content", "text", "output_text", "generated_text", "answer", "value")
    for key in direct_text_keys:
        if key in node:
            parts = _extract_text_parts(node[key], allow_reasoning=allow_reasoning, depth=depth + 1)
            if parts:
                return parts

    container_keys = ("message", "delta", "output", "response", "data", "result")
    for key in container_keys:
        if key in node:
            parts = _extract_text_parts(node[key], allow_reasoning=allow_reasoning, depth=depth + 1)
            if parts:
                return parts

    if allow_reasoning:
        for key in ("reasoning_content", "reasoning", "thought", "thinking"):
            if key in node:
                parts = _extract_text_parts(node[key], allow_reasoning=True, depth=depth + 1)
                if parts:
                    return parts

    return []


def _find_choices(data: dict) -> list[Any] | None:
    choices = data.get("choices")
    if isinstance(choices, list):
        return choices

    for key in ("data", "response", "result"):
        inner = data.get(key)
        if isinstance(inner, dict):
            found = _find_choices(inner)
            if found is not None:
                return found

    return None


def _extract_top_level_text(data: dict) -> str | None:
    for key in ("output_text", "output", "message"):
        if key in data:
            text = _join_text_parts(
                _extract_text_parts(data[key], allow_reasoning=False)
            )
            if text:
                return text

    for key in ("response", "data", "result"):
        inner = data.get(key)
        if isinstance(inner, dict):
            text = _extract_top_level_text(inner)
            if text:
                return text

    for key in ("output_text", "output", "message", "response", "data", "result"):
        if key in data:
            text = _join_text_parts(
                _extract_text_parts(data[key], allow_reasoning=True)
            )
            if text:
                return text

    return None


def _extract_choice_text(choice: dict) -> str | None:
    candidates = []
    for key in ("message", "delta"):
        value = choice.get(key)
        if value is not None:
            candidates.append(value)
    candidates.append(choice)

    for candidate in candidates:
        text = _join_text_parts(
            _extract_text_parts(candidate, allow_reasoning=False)
        )
        if text:
            return text

    for candidate in candidates:
        text = _join_text_parts(
            _extract_text_parts(candidate, allow_reasoning=True)
        )
        if text:
            return text

    return None


def _describe_shape(value: Any) -> str:
    if isinstance(value, dict):
        keys = sorted(str(key) for key in value.keys())
        return f"字段: {', '.join(keys[:10]) or '无'}"
    if isinstance(value, list):
        return f"列表长度: {len(value)}"
    return f"类型: {type(value).__name__}"


def extract_chat_completion_content(resp: httpx.Response) -> str:
    if resp.status_code >= 400:
        detail = None
        text = resp.text or ""
        if text.strip():
            try:
                detail = _extract_error_detail(resp.json())
            except (json.JSONDecodeError, ValueError):
                detail = _compact_preview(text)

        if resp.status_code in (401, 403):
            message = "API 认证失败，请检查 API Key"
            if detail:
                message = f"{message}：{detail}"
            raise RuntimeError(message)
        if resp.status_code == 429:
            message = "API 请求频率受限，请稍后重试"
            if detail:
                message = f"{message}：{detail}"
            raise RuntimeError(message)

        if detail:
            raise RuntimeError(f"API 请求失败 (HTTP {resp.status_code})：{detail}")
        raise RuntimeError(f"API 请求失败 (HTTP {resp.status_code})")

    data = _parse_response_json(resp)
    if not isinstance(data, dict):
        raise RuntimeError("AI 接口返回格式异常：顶层 JSON 不是对象")

    error_detail = _extract_error_detail(data)

    top_level_text = _extract_top_level_text(data)
    if top_level_text:
        return top_level_text

    choices = _find_choices(data)
    if choices is None:
        if error_detail:
            raise RuntimeError(f"AI 接口返回错误：{error_detail}")
        raise RuntimeError("AI 接口返回格式异常：缺少 choices 或 output")
    if not choices:
        if error_detail:
            raise RuntimeError(f"AI 接口返回错误：{error_detail}")
        raise RuntimeError("AI 接口返回格式异常：choices 为空")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise RuntimeError("AI 接口返回格式异常：choices[0] 不是对象")

    content = _extract_choice_text(first_choice)
    if content:
        return content

    if error_detail:
        raise RuntimeError(f"AI 接口返回错误：{error_detail}")

    raise RuntimeError(
        f"AI 接口返回格式异常：缺少可用的消息内容（choices[0] {_describe_shape(first_choice)}）"
    )
