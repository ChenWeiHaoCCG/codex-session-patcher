from __future__ import annotations

import asyncio

import httpx
import pytest

from web.backend.ai_service import call_llm
from web.backend.llm_client import build_ai_request
from web.backend.prompt_rewriter import rewrite_prompt
from web.backend.schemas import Settings


class _FakeAsyncClient:
    def __init__(self, response: httpx.Response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, *args, **kwargs):
        return self._response


def _patch_async_client(monkeypatch, module, response: httpx.Response):
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(response),
    )


def test_rewrite_prompt_reports_empty_response(monkeypatch):
    from web.backend import prompt_rewriter

    response = httpx.Response(
        200,
        text="",
        request=httpx.Request("POST", "https://example.com/chat/completions"),
    )
    _patch_async_client(monkeypatch, prompt_rewriter, response)

    with pytest.raises(RuntimeError, match="空响应"):
        asyncio.run(
            rewrite_prompt(
                "rewrite this",
                "https://example.com",
                "",
                "test-model",
            )
        )


def test_call_llm_reports_html_response(monkeypatch):
    from web.backend import ai_service

    response = httpx.Response(
        200,
        text="<html><body>Not Found</body></html>",
        headers={"content-type": "text/html; charset=utf-8"},
        request=httpx.Request("POST", "https://example.com/chat/completions"),
    )
    _patch_async_client(monkeypatch, ai_service, response)

    settings = Settings(ai_endpoint="https://example.com", ai_model="test-model")

    with pytest.raises(RuntimeError, match="HTML"):
        asyncio.run(call_llm(settings, [{"role": "user", "content": "test"}]))


def test_call_llm_returns_message_content(monkeypatch):
    from web.backend import ai_service

    response = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": "rewritten content",
                    }
                }
            ]
        },
        request=httpx.Request("POST", "https://example.com/chat/completions"),
    )
    _patch_async_client(monkeypatch, ai_service, response)

    settings = Settings(ai_endpoint="https://example.com", ai_model="test-model")
    result = asyncio.run(call_llm(settings, [{"role": "user", "content": "test"}]))

    assert result == "rewritten content"


def test_call_llm_supports_content_part_list(monkeypatch):
    from web.backend import ai_service

    response = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "output_text", "text": "part one"},
                            {"type": "text", "text": "part two"},
                        ]
                    }
                }
            ]
        },
        request=httpx.Request("POST", "https://example.com/chat/completions"),
    )
    _patch_async_client(monkeypatch, ai_service, response)

    settings = Settings(ai_endpoint="https://example.com", ai_model="test-model")
    result = asyncio.run(call_llm(settings, [{"role": "user", "content": "test"}]))

    assert result == "part one\npart two"


def test_call_llm_supports_nested_text_value(monkeypatch):
    from web.backend import ai_service

    response = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": {"value": "nested value"}}
                        ]
                    }
                }
            ]
        },
        request=httpx.Request("POST", "https://example.com/chat/completions"),
    )
    _patch_async_client(monkeypatch, ai_service, response)

    settings = Settings(ai_endpoint="https://example.com", ai_model="test-model")
    result = asyncio.run(call_llm(settings, [{"role": "user", "content": "test"}]))

    assert result == "nested value"


def test_call_llm_falls_back_to_reasoning_content(monkeypatch):
    from web.backend import ai_service

    response = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "fallback reasoning text",
                    }
                }
            ]
        },
        request=httpx.Request("POST", "https://example.com/chat/completions"),
    )
    _patch_async_client(monkeypatch, ai_service, response)

    settings = Settings(ai_endpoint="https://example.com", ai_model="test-model")
    result = asyncio.run(call_llm(settings, [{"role": "user", "content": "test"}]))

    assert result == "fallback reasoning text"


def test_call_llm_supports_top_level_output_text(monkeypatch):
    from web.backend import ai_service

    response = httpx.Response(
        200,
        json={"output_text": "top level text"},
        request=httpx.Request("POST", "https://example.com/chat/completions"),
    )
    _patch_async_client(monkeypatch, ai_service, response)

    settings = Settings(ai_endpoint="https://example.com", ai_model="test-model")
    result = asyncio.run(call_llm(settings, [{"role": "user", "content": "test"}]))

    assert result == "top level text"


def test_build_ai_request_for_chat_completions():
    endpoint, body = build_ai_request(
        "https://example.com/v1/chat/completions",
        "test-model",
        [{"role": "user", "content": "test"}],
    )

    assert endpoint == "https://example.com/v1/chat/completions"
    assert body["model"] == "test-model"
    assert body["messages"] == [{"role": "user", "content": "test"}]
    assert body["max_tokens"] == 1024


def test_build_ai_request_for_responses():
    endpoint, body = build_ai_request(
        "https://example.com/v1/responses",
        "test-model",
        [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "test"},
        ],
    )

    assert endpoint == "https://example.com/v1/responses"
    assert body["model"] == "test-model"
    assert body["instructions"] == "system prompt"
    assert body["input"] == [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "test"}],
        }
    ]
    assert body["max_output_tokens"] == 1024


def test_build_ai_request_for_responses_normalizes_message_parts():
    endpoint, body = build_ai_request(
        "https://example.com/v1/responses",
        "test-model",
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "part one"},
                    {"type": "output_text", "text": {"value": "part two"}},
                ],
            }
        ],
    )

    assert endpoint == "https://example.com/v1/responses"
    assert body["input"] == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "part one"},
                {"type": "input_text", "text": "part two"},
            ],
        }
    ]


def test_rewrite_prompt_falls_back_when_llm_errors(monkeypatch):
    from web.backend import prompt_rewriter as pr

    async def _boom(*args, **kwargs):
        raise RuntimeError("AI 接口返回格式异常：缺少 choices 或 output")

    monkeypatch.setattr(pr, "request_ai_text", _boom)

    rewritten, strategy = asyncio.run(
        pr.rewrite_prompt(
            "测试请求",
            "https://example.com/v1/responses",
            "",
            "test-model",
            target="claude_code",
            ctf_prompt="CTF prompt",
        )
    )

    assert "测试请求" in rewritten
    assert "授权" in rewritten or "CTF" in rewritten
    assert strategy in {"ctf", "pentest"}


def test_build_ai_request_for_responses_moves_system_to_instructions():
    endpoint, body = build_ai_request(
        "https://example.com/v1/responses",
        "test-model",
        [
            {"role": "system", "content": [{"type": "text", "text": "rule one"}]},
            {"role": "system", "content": "rule two"},
            {"role": "user", "content": "test"},
        ],
    )

    assert endpoint == "https://example.com/v1/responses"
    assert body["instructions"] == "rule one\n\nrule two"
    assert body["input"] == [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "test"}],
        }
    ]
