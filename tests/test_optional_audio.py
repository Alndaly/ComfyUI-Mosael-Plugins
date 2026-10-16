"""Unit tests for the optional audio nodes (no ComfyUI needed)."""

import pytest
import torch

from conftest import StubCoreLoadAudio, FakeImageTensor


def make_audio(seconds=2.0, sample_rate=1000, channels=1, batch=1):
    samples = int(seconds * sample_rate)
    return {
        "waveform": torch.linspace(-1.0, 1.0, samples).repeat(batch, channels, 1),
        "sample_rate": sample_rate,
    }


@pytest.fixture
def loader_cls(plugin):
    return plugin.NODE_CLASS_MAPPINGS["Optional Load Audio"]


@pytest.fixture
def loader(loader_cls):
    return loader_cls()


@pytest.fixture
def preview_cls(plugin):
    return plugin.NODE_CLASS_MAPPINGS["Optional Audio Preview"]


@pytest.fixture
def preview(preview_cls):
    return preview_cls()


@pytest.fixture
def edit_cls(plugin):
    return plugin.NODE_CLASS_MAPPINGS["Quick Audio Edit"]


@pytest.fixture
def edit(edit_cls):
    return edit_cls()


def make_audio_file(input_dir, name="clip.mp3", content=b"fake audio bytes"):
    path = input_dir / name
    path.write_bytes(content)
    return name


# --- Optional Load Audio -----------------------------------------------------

def test_input_types_offers_none_first(loader_cls, input_dir):
    make_audio_file(input_dir, "a.mp3")
    make_audio_file(input_dir, "b.flac")
    make_audio_file(input_dir, "clip.mp4")  # videos are valid audio sources
    make_audio_file(input_dir, "notes.txt")
    types = loader_cls.INPUT_TYPES()
    options = types["required"]["audio"][0]
    assert options[0] == "none"
    assert "a.mp3" in options and "b.flac" in options and "clip.mp4" in options
    assert "notes.txt" not in options
    assert types["required"]["audio"][1]["audio_upload"] is True
    assert types["required"]["allow_none"][1]["default"] is True


def test_return_types_export_components(loader_cls):
    assert loader_cls.RETURN_TYPES == ("AUDIO", "BOOLEAN", "INT", "FLOAT")
    assert loader_cls.RETURN_NAMES == ("audio", "has_audio", "sample_rate", "duration")


def test_none_selection_needs_no_file(loader, input_dir):
    audio, has_audio, sample_rate, duration = loader.load_audio("none", True)
    assert audio is None
    assert has_audio is False
    assert sample_rate == 0
    assert duration == 0.0


def test_none_selection_with_allow_none_disabled(loader, input_dir):
    with pytest.raises(ValueError, match="allow_none"):
        loader.load_audio("none", False)


def test_audio_selection_delegates_to_core_loader(loader, input_dir):
    make_audio_file(input_dir, "clip.mp3")
    waveform = FakeImageTensor((2, 44100))  # 2 channels, 1 second
    StubCoreLoadAudio.result = (waveform, 44100)
    audio, has_audio, sample_rate, duration = loader.load_audio("clip.mp3", True)
    assert has_audio is True
    assert audio["waveform"].shape == (1, 2, 44100)  # batch dim added
    assert audio["sample_rate"] == 44100
    assert sample_rate == 44100
    assert duration == pytest.approx(1.0)


def test_missing_file_is_an_error_not_missing(loader, input_dir):
    with pytest.raises(FileNotFoundError, match="deleted"):
        loader.load_audio("ghost.mp3", True)


def test_corrupted_audio_raises_clear_error(loader, input_dir):
    make_audio_file(input_dir, "broken.mp3")
    StubCoreLoadAudio.error = ValueError("no audio stream found")
    with pytest.raises(RuntimeError, match="broken.mp3"):
        loader.load_audio("broken.mp3", True)


def test_validate_inputs(loader_cls, input_dir):
    make_audio_file(input_dir, "ok.wav")
    assert loader_cls.VALIDATE_INPUTS("none", True) is True
    assert "allow_none" in loader_cls.VALIDATE_INPUTS("none", False)
    assert loader_cls.VALIDATE_INPUTS("ok.wav", True) is True
    assert "Invalid audio file" in loader_cls.VALIDATE_INPUTS("ghost.wav", True)


def test_is_changed_tracks_file_contents(loader_cls, input_dir):
    name = make_audio_file(input_dir, "a.mp3", b"v1")
    h1 = loader_cls.IS_CHANGED(name, True)
    assert h1 != loader_cls.IS_CHANGED("none", True)
    make_audio_file(input_dir, "a.mp3", b"v2")
    assert loader_cls.IS_CHANGED(name, True) != h1


# --- Optional Audio Preview --------------------------------------------------

def test_preview_input_types_declares_lazy_optional_audio(preview_cls):
    types = preview_cls.INPUT_TYPES()
    assert types["required"]["condition"][0] == "BOOLEAN"
    assert types["optional"]["audio"] == ("AUDIO", {"lazy": True})
    assert preview_cls.OUTPUT_NODE is True
    assert preview_cls.RETURN_TYPES == ("AUDIO",)


def test_check_lazy_status_requests_audio_only_when_condition_true(preview):
    assert preview.check_lazy_status(True, audio=None) == ["audio"]
    assert preview.check_lazy_status(False, audio=None) == []
    assert preview.check_lazy_status(True, audio=make_audio()) == []


def test_preview_skips_when_condition_false(preview):
    result = preview.preview(False, audio=make_audio())
    assert result == {"ui": {"audio": []}, "result": (None,)}


def test_preview_skips_when_audio_none(preview):
    result = preview.preview(True, audio=None)
    assert result == {"ui": {"audio": []}, "result": (None,)}


def test_preview_emits_ui_and_passes_through(preview):
    audio = make_audio()
    result = preview.preview(True, audio=audio)
    assert result["result"] == (audio,)
    assert result["ui"]["audio"]


# --- Quick Audio Edit --------------------------------------------------------

def test_edit_missing_audio_passes_through(edit):
    assert edit.edit(0.0, 0.0, 0.0, 0.0, 0.0, audio=None) == (None, 0.0)


def test_edit_noop_returns_same_data(edit):
    audio = make_audio(seconds=2.0)
    edited, duration = edit.edit(0.0, 0.0, 0.0, 0.0, 0.0, audio=audio)
    assert duration == pytest.approx(2.0)
    assert torch.equal(edited["waveform"], audio["waveform"])
    assert edited["sample_rate"] == audio["sample_rate"]


def test_edit_trim(edit):
    audio = make_audio(seconds=2.0, sample_rate=1000)
    edited, duration = edit.edit(0.5, 0.75, 0.0, 0.0, 0.0, audio=audio)
    assert duration == pytest.approx(0.75)
    assert edited["waveform"].shape[-1] == 750
    # same samples as the source slice — no resampling artifacts
    assert torch.equal(edited["waveform"], audio["waveform"][..., 500:1250])


def test_edit_trim_from_end_with_negative_start(edit):
    audio = make_audio(seconds=2.0, sample_rate=1000)
    edited, duration = edit.edit(-1.0, 0.0, 0.0, 0.0, 0.0, audio=audio)
    assert duration == pytest.approx(1.0)
    assert torch.equal(edited["waveform"], audio["waveform"][..., 1000:])


def test_edit_volume(edit):
    audio = make_audio(seconds=1.0)
    edited, _ = edit.edit(0.0, 0.0, -6.0, 0.0, 0.0, audio=audio)
    expected = audio["waveform"] * (10 ** (-6 / 20))
    assert torch.allclose(edited["waveform"], expected)


def test_edit_fade_in_and_out(edit):
    audio = make_audio(seconds=1.0, sample_rate=1000)
    edited, duration = edit.edit(0.0, 0.0, 0.0, 0.25, 0.25, audio=audio)
    assert duration == pytest.approx(1.0)
    wave = edited["waveform"]
    # fade-in: first sample near zero; middle (between the fades) untouched
    assert wave[..., 0].abs().item() < 0.01
    assert torch.allclose(wave[..., 250:750], audio["waveform"][..., 250:750])
    # fade-out: last sample near zero
    assert wave[..., -1].abs().item() < 0.01


def test_edit_fade_longer_than_clip_is_clamped(edit):
    audio = make_audio(seconds=0.5, sample_rate=1000)
    edited, _ = edit.edit(0.0, 0.0, 0.0, 10.0, 10.0, audio=audio)
    # both fades clamp to the clip; first sample silent, last sample silent
    assert edited["waveform"][..., 0].abs().item() < 0.01
    assert edited["waveform"][..., -1].abs().item() < 0.01


def test_edit_combined_operations(edit):
    audio = make_audio(seconds=4.0, sample_rate=1000)
    edited, duration = edit.edit(1.0, 2.0, 6.0, 0.5, 0.5, audio=audio)
    assert duration == pytest.approx(2.0)
    assert edited["waveform"].shape[-1] == 2000
    # middle (outside fades) got exactly the dB gain
    gain = 10 ** (6 / 20)
    assert torch.allclose(
        edited["waveform"][..., 500:1500],
        audio["waveform"][..., 1500:2500] * gain,
    )


def test_edit_preserves_batch_and_channels(edit):
    audio = make_audio(seconds=1.0, sample_rate=1000, channels=2, batch=3)
    edited, _ = edit.edit(0.0, 0.0, 0.0, 0.0, 0.0, audio=audio)
    assert edited["waveform"].shape == (3, 2, 1000)


def test_edit_widgets_allow_negative_start_and_gain(edit_cls):
    fields = edit_cls.INPUT_TYPES()["required"]
    assert fields["start_time"][1]["min"] < 0
    assert fields["volume_db"][1]["min"] < 0
    assert fields["duration"][1]["max"] > 2048  # long clips are valid


def test_one_sample_fade_is_applied(edit):
    audio = {"waveform": torch.ones(1, 1, 1), "sample_rate": 1000}
    result, duration = edit.edit(0, 0, 0, 0.01, 0, audio=audio)
    assert duration == 0.001
    assert result["waveform"].item() == 0
    assert audio["waveform"].item() == 1


def test_empty_audio_preview_clears_ui_and_preserves_the_audio(preview):
    audio = make_audio(seconds=0)
    result = preview.preview(True, audio=audio)
    assert result["ui"] == {"audio": []}
    assert result["result"][0] is audio


@pytest.mark.parametrize("dtype", [torch.float16, torch.float32])
def test_volume_widget_extremes_produce_finite_audio(edit_cls, edit, dtype):
    options = edit_cls.INPUT_TYPES()["required"]["volume_db"][1]
    audio = make_audio()
    audio["waveform"] = audio["waveform"].to(dtype)
    for gain in (options["min"], options["max"]):
        result, _ = edit.edit(0, 0, gain, 0, 0, audio=audio)
        assert torch.isfinite(result["waveform"]).all()
