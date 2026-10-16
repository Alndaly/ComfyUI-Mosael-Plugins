"""Translation node tests; all provider responses are mocked."""

import importlib
import io
import json
import urllib.error
from urllib.parse import parse_qs, urlparse

import pytest


@pytest.fixture
def translation(plugin):
    return importlib.import_module(plugin.__name__ + ".nodes.translation")


@pytest.fixture
def node(plugin):
    return plugin.NODE_CLASS_MAPPINGS["Text Translate"]()


@pytest.fixture
def http(monkeypatch):
    state = {"calls": [], "payload": [[["Hello", "你好"], [" world", "世界"]], None, "zh-CN"]}

    def urlopen(request, timeout=None):
        state["calls"].append((request, timeout))
        payload = state["payload"]
        if isinstance(payload, Exception):
            raise payload
        return io.BytesIO(payload if isinstance(payload, bytes) else json.dumps(payload).encode())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    return state


def test_google_request_and_segments(node, http):
    assert node.translate("你好世界 &?+#", "Google", target_language="en", timeout=12) == ("Hello world",)
    request, timeout = http["calls"][0]
    assert urlparse(request.full_url).netloc == "translate.googleapis.com"
    assert parse_qs(urlparse(request.full_url).query) == {
        "client": ["gtx"], "sl": ["auto"], "tl": ["en"],
        "dt": ["t"], "q": ["你好世界 &?+#"],
    }
    assert timeout == 12
    assert request.get_method() == "GET"


@pytest.mark.parametrize("text", ["", " \n\t"])
@pytest.mark.parametrize("engine", ["Google", "LLM"])
def test_blank_no_request(node, http, text, engine):
    assert node.translate(text, engine) == (text,)
    assert not http["calls"]


def test_google_ignores_llm_settings_and_preserves_boundary_space(node, http):
    assert node.translate(" \n你好\t ", "Google", base_url="", model="", api_key="secret") == (" \nHello world\t ",)
    request, _ = http["calls"][0]
    assert "Authorization" not in request.headers


def test_long_input_chunking(node, translation, http):
    text = "你好，世界。 " * 700 + "末尾"
    chunks = list(translation._chunks(text))
    assert "".join(chunks) == text
    assert all(0 < len(chunk) <= 1000 for chunk in chunks)
    result, = node.translate(text, "Google")
    submitted = [parse_qs(urlparse(req.full_url).query)["q"][0] for req, _ in http["calls"]]
    assert submitted == [chunk.strip() for chunk in chunks if chunk.strip()]
    assert result == "".join(
        chunk[:len(chunk) - len(chunk.lstrip())] + "Hello world" + chunk[len(chunk.rstrip()):]
        if chunk.strip() else chunk for chunk in chunks
    )


def test_unbroken_text_chunking(translation):
    assert list(translation._chunks("中" * 2001)) == ["中" * 1000, "中" * 1000, "中"]


@pytest.mark.parametrize("payload", [None, {}, [], [None], [[]], [[[None]]], [[[123]]], [[[""]]], b"not json", b"\xff"])
def test_google_bad_response(node, http, payload):
    http["payload"] = payload
    with pytest.raises(RuntimeError, match="Google Translate"):
        node.translate("你好", "Google")


@pytest.mark.parametrize("error,match", [
    (urllib.error.HTTPError("url", 429, "Too Many Requests", {}, None), "HTTP 429"),
    (urllib.error.URLError("offline"), "network/proxy"),
    (TimeoutError("timeout"), "network/proxy"),
])
def test_google_network_errors(node, http, error, match):
    http["payload"] = error
    with pytest.raises(RuntimeError, match=match):
        node.translate("你好", "Google")


@pytest.mark.parametrize("engine,kwargs", [
    ("invalid", {}), ("Google", {"target_language": "auto"}),
    ("LLM", {"target_language": " "}),
    ("Google", {"target_language": "English" + " language"}),
    ("LLM", {"base_url": " "}), ("LLM", {"model": ""}),
])
def test_invalid_configuration(node, http, engine, kwargs):
    with pytest.raises(ValueError):
        node.translate("你好", engine, **kwargs)
    assert not http["calls"]


def test_llm_uses_existing_client(node, http):
    http["payload"] = {"choices": [{"message": {"content": "翻译结果"}}]}
    assert node.translate(
        "Hello\nworld", "LLM", source_language="English", target_language="简体中文",
        base_url=" https://example.com/v1/ ", model=" custom-model ", api_key="key",
        instructions="保留术语 ComfyUI", temperature=0.3, max_tokens=4000, timeout=45,
    ) == ("翻译结果",)
    request, timeout = http["calls"][0]
    body = json.loads(request.data)
    assert request.full_url == "https://example.com/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer key"
    assert body["model"] == "custom-model"
    assert body["temperature"] == 0.3
    assert body["max_tokens"] == 4000
    assert "response_format" not in body
    assert timeout == 45
    system, user = body["messages"]
    assert "English into 简体中文" in system["content"]
    assert "保留术语 ComfyUI" in system["content"]
    assert user == {"role": "user", "content": "Hello\nworld"}


def test_llm_auto_and_defaults(node, http):
    http["payload"] = {"choices": [{"message": {"content": "Hello"}}]}
    assert node.translate("你好", "LLM") == ("Hello",)
    request, _ = http["calls"][0]
    body = json.loads(request.data)
    assert "automatically detected" in body["messages"][0]["content"]
    assert "max_tokens" not in body
    assert "Authorization" not in request.headers


def test_llm_empty_response(node, http):
    http["payload"] = {"choices": [{"message": {"content": None}}]}
    with pytest.raises(RuntimeError, match="empty translation"):
        node.translate("你好", "LLM")


def test_registered_schema(plugin, node):
    assert plugin.NODE_DISPLAY_NAME_MAPPINGS["Text Translate"] == "Text Translate"
    schema = node.INPUT_TYPES()
    assert schema["required"]["engine"][0] == ["Google", "LLM"]
    assert node.RETURN_TYPES == ("STRING",)
    assert callable(getattr(node, node.FUNCTION))
