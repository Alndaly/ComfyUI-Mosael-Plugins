"""Contract checks through a real ComfyUI server, without external API calls."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from comfy_client import ComfyClient
from test_node_contracts import NODE_NAMES

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def live_client():
    client = ComfyClient(os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188"))
    if not client.reachable():
        pytest.skip("ComfyUI server not reachable")
    return client


@pytest.mark.parametrize("name", NODE_NAMES)
def test_live_node_metadata(live_client, name):
    metadata = live_client.object_info(name)[name]
    assert len(metadata["output"]) == len(metadata["output_name"])
    assert metadata["category"].startswith("Optional Inputs/")
    assert metadata["input"]
    if name in ("Optional Audio Preview", "Optional Video Preview"):
        assert metadata["output_node"] is True


@pytest.mark.parametrize("node_name,field", [("Optional Audio Preview", "audio"), ("Optional Video Preview", "images")])
def test_live_empty_preview_clears_ui(live_client, node_name, field):
    ok, entry = live_client.run({"1": {"class_type": node_name, "inputs": {"condition": False}}})
    assert ok, entry
    assert entry["outputs"]["1"][field] == []


def test_presence_and_any_switch_use_missing_image(live_client):
    workflow = {
        "1": {"class_type": "Optional Image", "inputs": {}},
        "2": {"class_type": "Has Image", "inputs": {"image": ["1", 0]}},
        "3": {"class_type": "Lazy Any Switch", "inputs": {"condition": ["2", 0], "value_true": "present", "value_false": "missing"}},
        "4": {"class_type": "OI Test String Output", "inputs": {"string": ["3", 0]}},
    }
    ok, entry = live_client.run(workflow)
    assert ok, entry
    assert entry["outputs"]["4"]["text"] == ["missing"]


@pytest.fixture
def completion_server():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body))
            result = {"choices": [{"finish_reason": "stop", "message": {"content": "mock translation"}}]}
            payload = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:{}/v1".format(server.server_port), requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("node_name", ["LLM API Call", "Text Translate"])
def test_live_custom_llm(live_client, completion_server, node_name):
    base_url, requests = completion_server
    inputs = {"base_url": base_url, "model": "mock-model"}
    if node_name == "LLM API Call":
        inputs.update(prompt="Hello", system_prompt="Translate", api_key="", temperature=0.2, max_tokens=100, timeout=10, response_format="text")
    else:
        # Omitting optional widgets must use the Python defaults.
        inputs.update(text="Hello", engine="LLM", source_language="auto", target_language="zh-CN")
    ok, entry = live_client.run({
        "1": {"class_type": node_name, "inputs": inputs},
        "2": {"class_type": "OI Test String Output", "inputs": {"string": ["1", 0]}},
    })
    assert ok, entry
    assert entry["outputs"]["2"]["text"] == ["mock translation"]
    assert requests[0][0] == "/v1/chat/completions"
    assert requests[0][1]["model"] == "mock-model"


def test_live_google_blank_text_skips_network(live_client):
    ok, entry = live_client.run({
        "1": {"class_type": "Text Translate", "inputs": {"text": "", "engine": "Google", "source_language": "auto", "target_language": "en"}},
        "2": {"class_type": "OI Test String Output", "inputs": {"string": ["1", 0]}},
    })
    assert ok, entry
    assert entry["outputs"]["2"]["text"] == [""]


@pytest.mark.parametrize("node_name", ["FunASR Transcribe", "VAD Auto Trim Audio"])
def test_live_empty_audio_speech_nodes(live_client, node_name):
    inputs = {"audio": ["1", 0]}
    if node_name == "FunASR Transcribe":
        inputs.update(asr_model="unused-model", use_vad=False, use_punctuation=False)
        field = "string"
        sink = "OI Test String Output"
    else:
        inputs.update(vad_model="unused-model", padding=0, min_speech=0, merge_gap=0)
        field = "audio"
        sink = "OI Test Audio Output"
    workflow = {
        "1": {"class_type": "OI Test Empty Audio", "inputs": {}},
        "2": {"class_type": node_name, "inputs": inputs},
        "3": {"class_type": sink, "inputs": {field: ["2", 0]}},
    }
    ok, entry = live_client.run(workflow)
    assert ok, entry


def test_live_latent_switch_requires_no_checkpoint(live_client):
    ok, entry = live_client.run({
        "1": {"class_type": "OI Test Constant Latent", "inputs": {}},
        "2": {"class_type": "OI Test Fail Latent", "inputs": {}},
        "3": {"class_type": "Lazy Latent Switch", "inputs": {"condition": True, "latent_true": ["1", 0], "latent_false": ["2", 0]}},
        "4": {"class_type": "OI Test Latent Output", "inputs": {"latent": ["3", 0]}},
    })
    assert ok, entry
    assert entry["outputs"]["4"]["shape"] == [[1, 4, 8, 8]]


def test_live_cached_vad_roundtrip(live_client):
    model = os.environ.get("COMFYUI_FUNASR_VAD_MODEL")
    if not model:
        pytest.skip("set COMFYUI_FUNASR_VAD_MODEL to an already cached local model directory")
    from pathlib import Path
    name = live_client.upload_image((Path(__file__).parent / "tiny_speech.flac").read_bytes(), name="oi_audit_speech.flac")
    ok, entry = live_client.run({
        "1": {"class_type": "Optional Load Audio", "inputs": {"audio": name, "allow_none": True}},
        "2": {"class_type": "VAD Auto Trim Audio", "inputs": {"audio": ["1", 0], "vad_model": model, "padding": 0.123456, "min_speech": 0.05, "merge_gap": 0.2}},
        "3": {"class_type": "Audio Trim by Segments", "inputs": {"audio": ["1", 0], "segments": ["2", 1]}},
        "4": {"class_type": "OI Test Audio Output", "inputs": {"audio": ["2", 0]}},
        "5": {"class_type": "OI Test Audio Output", "inputs": {"audio": ["3", 0]}},
    })
    assert ok, entry
    assert entry["outputs"]["4"]["shape"] == entry["outputs"]["5"]["shape"]


def test_live_zero_sample_audio_preview(live_client):
    ok, entry = live_client.run({
        "1": {"class_type": "OI Test Empty Audio", "inputs": {}},
        "2": {"class_type": "Optional Audio Preview", "inputs": {"condition": True, "audio": ["1", 0]}},
    })
    assert ok, entry
    assert entry["outputs"]["2"]["audio"] == []
