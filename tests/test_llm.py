import json
import time
from pathlib import Path

import pytest

from ainovel.llm.classify import classify_exception
from ainovel.llm.errors import ProviderError
from ainovel.llm.litellm_client import LiteLLMTransport
from ainovel.llm.policy import RoleClient
from ainovel.llm.stream import aggregate_chunks, read_until_idle
from ainovel.llm.types import Completion, ModelRef, RoleModel


def _role() -> RoleModel:
    return RoleModel(
        primary=ModelRef(provider="primary", model="main"),
        fallbacks=[ModelRef(provider="backup", model="spare")],
    )


class _Script:
    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.models: list[str] = []

    def complete(self, model: ModelRef, messages: list[dict], tools: list[dict]) -> Completion:
        self.models.append(model.model)
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_rate_limit_switches_to_fallback():
    script = _Script([ProviderError("限流", kind="rate_limit", status=429), Completion(content="好")])
    client = RoleClient(_role(), script, sleep=lambda _: None)
    result = client.complete([], [])
    assert result.content == "好"
    assert script.models == ["main", "spare"]


def test_unavailable_switches_to_fallback():
    script = _Script([ProviderError("不可用", kind="unavailable", status=503), Completion(content="好")])
    client = RoleClient(_role(), script, sleep=lambda _: None)
    assert client.complete([], []).content == "好"
    assert script.models == ["main", "spare"]


def test_auth_is_not_retried_and_does_not_use_fallback():
    script = _Script([ProviderError("鉴权失败", kind="auth", status=401), Completion(content="不该走到")])
    client = RoleClient(_role(), script, sleep=lambda _: None)
    with pytest.raises(ProviderError, match="鉴权"):
        client.complete([], [])
    assert script.models == ["main"]


def test_model_not_found_is_not_retried():
    script = _Script([ProviderError("没有这个模型", kind="model_not_found", status=404)])
    client = RoleClient(_role(), script, sleep=lambda _: None)
    with pytest.raises(ProviderError, match="没有这个模型"):
        client.complete([], [])
    assert script.models == ["main"]


def test_timeout_retries_same_provider_then_raises():
    script = _Script([ProviderError("超时", kind="timeout")] * 3)
    client = RoleClient(_role(), script, sleep=lambda _: None)
    with pytest.raises(ProviderError, match="超时"):
        client.complete([], [])
    assert script.models == ["main", "main", "main"]


def test_timeout_succeeds_on_the_third_attempt():
    script = _Script(
        [ProviderError("超时", kind="timeout"), ProviderError("超时", kind="timeout"), Completion(content="成")]
    )
    client = RoleClient(_role(), script, sleep=lambda _: None)
    assert client.complete([], []).content == "成"
    assert script.models == ["main", "main", "main"]


def test_classify_status_codes():
    class RateLimitError(Exception):
        status_code = 429

    class AuthenticationError(Exception):
        status_code = 401

    assert classify_exception(RateLimitError("busy")).kind == "rate_limit"
    assert classify_exception(AuthenticationError("no")).kind == "auth"
    assert classify_exception(ProviderError("已分类", kind="timeout")).kind == "timeout"
    assert classify_exception(RuntimeError("别的")).kind == "unknown"


def test_stream_aggregates_split_tool_arguments():
    chunks = [
        {"choices": [{"delta": {"content": "先"}, "finish_reason": None}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "id": "call-1", "function": {"name": "echo", "arguments": '{"n":'}}
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {"content": "说", "tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]},
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ]
    seen: list[str] = []
    completion = aggregate_chunks(chunks, on_delta=seen.append)
    assert completion.content == "先说"
    assert seen == ["先", "说"]
    assert completion.stop_reason == "tool_calls"
    assert completion.tool_calls[0].name == "echo"
    assert json.loads(completion.tool_calls[0].arguments) == {"n": 1}


def test_stream_idle_times_out():
    def slow():
        time.sleep(0.2)
        yield {"choices": [{"delta": {"content": "晚了"}}]}

    with pytest.raises(ProviderError, match="流空闲") as caught:
        read_until_idle(slow(), 0.05)
    assert caught.value.kind == "stream_idle"


def test_litellm_transport_streams_and_classifies_auth():
    def completion(**kwargs):
        assert kwargs["stream"] is True
        assert kwargs["model"] == "openai/demo"
        assert kwargs["api_key"] == "secret"
        return [
            {"choices": [{"delta": {"content": "流"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "式"}, "finish_reason": "stop"}]},
        ]

    transport = LiteLLMTransport(completion=completion, idle_timeout=None)
    result = transport.complete(
        ModelRef(provider="openai", model="demo", api_key="secret"),
        [{"role": "user", "content": "hi"}],
        [],
    )
    assert result.content == "流式"
    assert result.stop_reason == "stop"

    class AuthenticationError(Exception):
        status_code = 401

    def denied(**kwargs):
        raise AuthenticationError("bad key")

    with pytest.raises(ProviderError) as caught:
        LiteLLMTransport(completion=denied, idle_timeout=None).complete(
            ModelRef(provider="openai", model="demo"),
            [],
            [],
        )
    assert caught.value.kind == "auth"


def test_loop_sources_do_not_name_novel_roles_or_tools():
    root = Path(__file__).parents[1] / "src" / "ainovel"
    banned = ("commit_chapter", "save_review", "architect", "writer", "editor", "outline", "premise")
    for relative in (
        "agents/loop.py",
        "agents/guard.py",
        "llm/policy.py",
        "llm/litellm_client.py",
        "llm/stream.py",
        "llm/classify.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        for word in banned:
            assert word not in text, relative
