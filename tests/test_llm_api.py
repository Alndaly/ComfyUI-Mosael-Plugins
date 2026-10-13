"""Unit tests for the LLM API Call node (no network access)."""

import io
import json
import urllib.error

import pytest


@pytest.fixture
def llm_cls(plugin):
    return plugin.NODE_CLASS_MAPPINGS["LLM API Call"]


@pytest.fixture
def llm(llm_cls):
    return llm_cls()


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


@pytest.fixture
def http_calls(monkeypatch):
    """Capture urllib requests; respond with a configurable JSON payload."""
    calls = {"request": None, "response": {"choices": [{"message": {"content": "Hello!"}}]}}

    def fake_urlopen(req, timeout=None):
        calls["request"] = {
            "url": req.full_url,
            "method": req.get_method(),
            "headers": dict(req.headers),
            "body": json.loads(req.data.decode("utf-8")),
            "timeout": timeout,
        }
        payload = calls["response"]
        if isinstance(payload, Exception):
            raise payload
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return calls


def base_kwargs(**overrides):
    kwargs = {
        "base_url": "https://api.example.com/v1/",
        "model": "test-model",
        "prompt": "Say hi",
        "system_prompt": "You are terse.",
        "api_key": "sk-secret",
        "temperature": 0.5,
        "max_tokens": 128,
        "timeout": 30.0,
        "response_format": "text",
    }
    kwargs.update(overrides)
    return kwargs


def test_request_shape(llm, http_calls):
    (response,) = llm.call(**base_kwargs())
    assert response == "Hello!"
    req = http_calls["request"]
    # trailing slash on base_url must not double up
    assert req["url"] == "https://api.example.com/v1/chat/completions"
    assert req["method"] == "POST"
    assert req["headers"]["Authorization"] == "Bearer sk-secret"
    assert req["timeout"] == 30.0
    body = req["body"]
    assert body["model"] == "test-model"
    assert body["temperature"] == 0.5
    assert body["max_tokens"] == 128
    assert body["messages"] == [
        {"role": "system", "content": "You are terse."},
        {"role": "user", "content": "Say hi"},
    ]


def test_system_prompt_omitted_when_blank(llm, http_calls):
    llm.call(**base_kwargs(system_prompt="   "))
    messages = http_calls["request"]["body"]["messages"]
    assert messages == [{"role": "user", "content": "Say hi"}]


def test_no_auth_header_without_api_key(llm, http_calls):
    llm.call(**base_kwargs(api_key=""))
    assert "Authorization" not in http_calls["request"]["headers"]


def test_max_tokens_zero_omitted(llm, http_calls):
    llm.call(**base_kwargs(max_tokens=0))
    assert "max_tokens" not in http_calls["request"]["body"]


def test_http_error_includes_body(llm, http_calls):
    http_calls["response"] = urllib.error.HTTPError(
        "url", 401, "Unauthorized", {}, io.BytesIO(b'{"error": "bad key"}')
    )
    with pytest.raises(RuntimeError, match="HTTP 401.*bad key"):
        llm.call(**base_kwargs())


def test_url_error_mentions_base_url(llm, http_calls):
    import socket
    http_calls["response"] = urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided"))
    with pytest.raises(RuntimeError, match="Could not reach LLM API"):
        llm.call(**base_kwargs())


def test_unexpected_response_shape_raises(llm, http_calls):
    http_calls["response"] = {"unexpected": True}
    with pytest.raises(RuntimeError, match="Unexpected LLM API response"):
        llm.call(**base_kwargs())


def test_content_parts_are_joined(llm, http_calls):
    # reasoning-style providers returning content as a list of parts
    http_calls["response"] = {"choices": [{"message": {"content": [
        {"type": "text", "text": "part one "},
        {"type": "text", "text": "part two"},
    ]}}]}
    (response,) = llm.call(**base_kwargs())
    assert response == "part one part two"


def test_null_content_becomes_empty_string(llm, http_calls):
    http_calls["response"] = {"choices": [{"message": {"content": None}}]}
    (response,) = llm.call(**base_kwargs())
    assert response == ""


def test_json_mode_sets_response_format(llm, http_calls):
    llm.call(**base_kwargs(response_format="json_object"))
    assert http_calls["request"]["body"]["response_format"] == {"type": "json_object"}


def test_text_mode_omits_response_format(llm, http_calls):
    llm.call(**base_kwargs(response_format="text"))
    assert "response_format" not in http_calls["request"]["body"]


def test_registered(plugin):
    assert "LLM API Call" in plugin.NODE_CLASS_MAPPINGS
