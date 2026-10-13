"""Unit tests for the FunASR nodes (no funasr package needed).

FunASR itself is stubbed: these tests exercise the plugin's own logic —
segment parsing/merging/trimming, missing-audio pass-through, and the
clear install hint when funasr is absent.
"""

import json
import sys
import types

import pytest
import torch


def make_audio(seconds=4.0, sample_rate=1000, channels=1):
    samples = int(seconds * sample_rate)
    return {
        "waveform": torch.linspace(-1.0, 1.0, samples).repeat(1, channels, 1),
        "sample_rate": sample_rate,
    }


@pytest.fixture
def plugin_nodes(plugin):
    return plugin.NODE_CLASS_MAPPINGS


@pytest.fixture
def funasr_module(plugin):
    """The plugin's funasr_nodes module, loaded the way ComfyUI loads it."""
    import importlib
    return importlib.import_module("comfyui_optional_inputs_under_test.nodes.funasr_nodes")


@pytest.fixture
def transcribe(plugin_nodes):
    return plugin_nodes["FunASR Transcribe"]()


@pytest.fixture
def vad_trim(plugin_nodes):
    return plugin_nodes["VAD Auto Trim Audio"]()


@pytest.fixture
def trim_by_segments(plugin_nodes):
    return plugin_nodes["Audio Trim by Segments"]()


@pytest.fixture
def funasr_stub(monkeypatch, funasr_module):
    """Install a fake funasr module with a controllable AutoModel."""
    calls = {}

    class FakeAutoModel:
        def __init__(self, **kwargs):
            calls["init_kwargs"] = kwargs

        def generate(self, input, fs=None, **kwargs):
            return calls.setdefault("results", [{"value": [[0, 1000], [2000, 3000]]}])

    fake = types.ModuleType("funasr")
    fake.AutoModel = FakeAutoModel
    monkeypatch.setitem(sys.modules, "funasr", fake)
    monkeypatch.setattr(funasr_module, "_MODEL_CACHE", {})
    return calls


# --- shared helpers -----------------------------------------------------------

def test_parse_segments_basic(plugin):
    from comfyui_optional_inputs_under_test.nodes.funasr_nodes import _parse_segments
    assert _parse_segments("[[0.0, 1.5], [2.0, 3.0]]") == [[0.0, 1.5], [2.0, 3.0]]


def test_parse_segments_tolerant(plugin):
    from comfyui_optional_inputs_under_test.nodes.funasr_nodes import _parse_segments
    # trailing commas, whitespace, object form, unordered, invalid pairs
    assert _parse_segments("[[0, 1], [2, 3],]") == [[0.0, 1.0], [2.0, 3.0]]
    assert _parse_segments('[{"start": 0.5, "end": 1.0}]') == [[0.5, 1.0]]
    assert _parse_segments("[[2, 3], [0, 1]]") == [[0.0, 1.0], [2.0, 3.0]]
    assert _parse_segments("[[1.0, 1.0], [0, 0]]") == []  # empty/invalid dropped
    assert _parse_segments("") == []


def test_parse_segments_rejects_garbage(plugin):
    from comfyui_optional_inputs_under_test.nodes.funasr_nodes import _parse_segments
    with pytest.raises(ValueError, match="not valid JSON"):
        _parse_segments("hello world")


def test_merge_segments(plugin):
    from comfyui_optional_inputs_under_test.nodes.funasr_nodes import _merge_segments
    segs = [[0.0, 1.0], [1.2, 2.0], [5.0, 6.0]]
    assert _merge_segments(segs, 0.4) == [[0.0, 2.0], [5.0, 6.0]]
    assert _merge_segments(segs, 0.1) == segs


def test_slice_audio_concatenates(plugin):
    from comfyui_optional_inputs_under_test.nodes.funasr_nodes import _slice_audio
    audio = make_audio(seconds=4.0, sample_rate=1000)
    out = _slice_audio(audio, [[0.5, 1.0], [2.0, 3.0]])
    assert out["sample_rate"] == 1000
    assert out["waveform"].shape[-1] == 1500
    assert torch.equal(out["waveform"][..., :500], audio["waveform"][..., 500:1000])
    assert torch.equal(out["waveform"][..., 500:], audio["waveform"][..., 2000:3000])


def test_slice_audio_empty_segments(plugin):
    from comfyui_optional_inputs_under_test.nodes.funasr_nodes import _slice_audio
    audio = make_audio(seconds=1.0, sample_rate=1000)
    out = _slice_audio(audio, [])
    assert out["waveform"].shape[-1] == 0
    assert out["sample_rate"] == 1000


# --- FunASR Transcribe -------------------------------------------------------

def test_transcribe_missing_audio_passes_through(transcribe):
    text, chars = transcribe.transcribe("paraformer-zh", True, True, audio=None)
    assert text == ""
    assert json.loads(chars) == []


def test_transcribe_requires_funasr(transcribe, monkeypatch, funasr_module):
    monkeypatch.setitem(sys.modules, "funasr", None)  # blocks "import funasr"
    monkeypatch.setattr(funasr_module, "_MODEL_CACHE", {})
    with pytest.raises(RuntimeError, match="pip install funasr"):
        transcribe.transcribe("paraformer-zh", False, False, audio=make_audio())


def test_transcribe_returns_text_and_char_timestamps(transcribe, funasr_stub):
    funasr_stub["results"] = [{
        "text": "你好世界",
        "timestamp": [[100, 200], [200, 300], [350, 450], [500, 600]],
    }]
    text, chars = transcribe.transcribe("paraformer-zh", False, False, audio=make_audio())
    assert text == "你好世界"
    parsed = json.loads(chars)
    assert len(parsed) == 4
    assert parsed[0] == {"index": 0, "start": 0.1, "end": 0.2}
    assert parsed[3] == {"index": 3, "start": 0.5, "end": 0.6}


def test_transcribe_handles_empty_result(transcribe, funasr_stub):
    funasr_stub["results"] = [{}]
    text, chars = transcribe.transcribe("paraformer-zh", False, False, audio=make_audio())
    assert text == ""
    assert json.loads(chars) == []


# --- VAD Auto Trim Audio -----------------------------------------------------

def test_vad_trim_missing_audio_passes_through(vad_trim):
    audio, segments, duration = vad_trim.trim(0.2, 0.1, 0.4, "fsmn-vad", audio=None)
    assert audio is None
    assert segments == "[]"
    assert duration == 0.0


def test_vad_trim_filters_merges_pads_and_slices(vad_trim, funasr_stub):
    # speech at [0, 1s] and [2.05, 3s]; gap 0.05s < merge_gap 0.4 -> merged
    funasr_stub["results"] = [{"value": [[0, 1000], [2050, 3000], [3500, 3520]]}]
    audio = make_audio(seconds=4.0, sample_rate=1000)
    trimmed, segments, duration = vad_trim.trim(
        padding=0.2, min_speech=0.1, merge_gap=0.4, vad_model="fsmn-vad", audio=audio)
    # [3.5, 3.52] dropped by min_speech; the other two stay separate
    # (gap 1.05s > merge_gap 0.4) and get padding 0.2 clamped to the clip
    assert json.loads(segments) == [[0.0, 1.2], [1.85, 3.2]]
    assert duration == pytest.approx(2.55)
    assert trimmed["waveform"].shape[-1] == 2550


def test_vad_trim_padding_clamped_to_clip(vad_trim, funasr_stub):
    funasr_stub["results"] = [{"value": [[100, 200]]}]
    audio = make_audio(seconds=1.0, sample_rate=1000)
    trimmed, segments, duration = vad_trim.trim(
        padding=5.0, min_speech=0.0, merge_gap=0.0, vad_model="fsmn-vad", audio=audio)
    assert json.loads(segments) == [[0.0, 1.0]]
    assert duration == pytest.approx(1.0)


# --- Audio Trim by Segments (manual second pass) -----------------------------

def test_trim_by_segments_missing_audio(trim_by_segments):
    audio, duration = trim_by_segments.trim("[[0, 1]]", audio=None)
    assert audio is None
    assert duration == 0.0


def test_trim_by_segments_roundtrip_with_vad_output(vad_trim, trim_by_segments, funasr_stub):
    # The exact workflow a user follows: auto-trim, take the segments string,
    # hand-edit it, and re-trim the ORIGINAL audio.
    funasr_stub["results"] = [{"value": [[0, 1000], [2000, 3000]]}]
    original = make_audio(seconds=4.0, sample_rate=1000)
    _, segments, _ = vad_trim.trim(0.1, 0.0, 0.4, "fsmn-vad", audio=original)

    edited = json.loads(segments)
    edited[0][1] = 0.5  # user shortens the first kept region
    retrimmed, duration = trim_by_segments.trim(json.dumps(edited), audio=original)
    # [[0, 0.5]] + [[1.9, 3.1]] = 0.5 + 1.2 seconds of audio
    assert duration == pytest.approx(1.7)
    assert retrimmed["waveform"].shape[-1] == 1700


def test_trim_by_segments_accepts_hand_edited_strings(trim_by_segments):
    audio = make_audio(seconds=3.0, sample_rate=1000)
    # trailing comma, extra spaces — must still parse
    _, duration = trim_by_segments.trim(" [[0.0 , 1.0], [2.0, 3.0],] ", audio=audio)
    assert duration == pytest.approx(2.0)


def test_trim_by_segments_invalid_json_raises_clear_error(trim_by_segments):
    audio = make_audio(seconds=1.0, sample_rate=1000)
    with pytest.raises(ValueError, match="not valid JSON"):
        trim_by_segments.trim("not json", audio=audio)
