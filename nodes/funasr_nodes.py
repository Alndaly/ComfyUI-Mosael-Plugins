"""Speech-to-text and VAD-based smart audio trimming via FunASR (optional).

FunASR (https://github.com/modelscope/FunASR) is an *optional* dependency:
these nodes register normally so workflows load on any machine, but they
raise a clear install hint when executed without the package.  Works on
Windows, Linux and macOS; models are downloaded on first use into the local
ModelScope cache (~/.cache/modelscope or %USERPROFILE%\\.cache\\modelscope).

Nodes:

* ``FunASR Transcribe`` — AUDIO -> transcribed text plus per-character
  timestamps (the "verbatim transcript", 逐字稿).
* ``VAD Auto Trim Audio`` — speech-activity detection trims silence away;
  outputs the trimmed audio plus the segment list as an editable JSON
  string.
* ``Audio Trim by Segments`` — the companion for manual second-pass
  editing: take the segments string produced above, edit the numbers by
  hand (or programmatically), and re-trim the *original* audio with them.
"""

import json

from ..utils.optional_values import has_value

# AutoModel instances are expensive to construct; cache one per config.
# Keyed by the constructor kwargs the node can influence.
_MODEL_CACHE = {}


class FunASRNotInstalled(RuntimeError):
    pass


def _funasr_automodel():
    try:
        from funasr import AutoModel
    except ImportError as e:
        raise FunASRNotInstalled(
            "FunASR nodes require the optional 'funasr' package "
            "(https://github.com/modelscope/FunASR). Install it into the "
            "same Python environment as ComfyUI:\n"
            "    pip install funasr\n"
            "Then restart ComfyUI. Works on Windows, Linux and macOS."
        ) from e
    return AutoModel


def _get_model(**kwargs):
    key = tuple(sorted(kwargs.items()))
    model = _MODEL_CACHE.get(key)
    if model is None:
        model = _funasr_automodel()(disable_update=True, **kwargs)
        _MODEL_CACHE[key] = model
    return model


def _audio_seconds(audio) -> float:
    return float(audio["waveform"].shape[-1]) / float(audio["sample_rate"])


def _slice_audio(audio, segments):
    """Return a new AUDIO dict holding the concatenation of [start, end)
    segments (seconds). Samples are referenced, not resampled."""
    import torch

    waveform = audio["waveform"]
    sample_rate = audio["sample_rate"]
    pieces = []
    for start, end in segments:
        s = max(0, int(round(start * sample_rate)))
        e = min(waveform.shape[-1], int(round(end * sample_rate)))
        if e > s:
            pieces.append(waveform[..., s:e])
    if not pieces:
        length = 0
        cat = torch.zeros(tuple(waveform.shape[:-1]) + (0,),
                          dtype=waveform.dtype, device=waveform.device)
    else:
        cat = torch.cat(pieces, dim=-1)
    return {"waveform": cat, "sample_rate": sample_rate}


def _parse_segments(segments_json) -> list:
    """Parse a segments string into [[start, end], ...] seconds.

    Accepts the output of VAD Auto Trim Audio plus small hand edits
    (trailing commas, extra whitespace, list-of-objects form).
    """
    if isinstance(segments_json, (list, tuple)):
        raw = segments_json
    else:
        text = str(segments_json).strip()
        if not text:
            return []
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            # tolerate hand edits: trailing commas before ] or }
            import re
            cleaned = re.sub(r",\s*([\]}])", r"\1", text)
            try:
                raw = json.loads(cleaned)
            except json.JSONDecodeError as e:
                raise ValueError(
                    "Segments is not valid JSON. Expected e.g. [[0.0, 2.1], [3.2, 5.0]], "
                    "got: {!r}".format(str(segments_json)[:200])
                ) from e
    segments = []
    for item in raw:
        if isinstance(item, dict):
            item = [item.get("start"), item.get("end")]
        start, end = float(item[0]), float(item[1])
        if end > start:
            segments.append([start, end])
    segments.sort()
    return segments


def _merge_segments(segments, merge_gap):
    """Merge segments separated by less than merge_gap seconds."""
    merged = []
    for start, end in segments:
        if merged and start - merged[-1][1] < merge_gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _format_segments(segments) -> str:
    return json.dumps([[round(s, 3), round(e, 3)] for s, e in segments])


class FunASRTranscribe:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "optional": {
                "audio": ("AUDIO",),
            },
            "required": {
                "asr_model": ("STRING", {"default": "paraformer-zh",
                                         "tooltip": "FunASR ASR model id, e.g. paraformer-zh / paraformer-en / SenseVoiceSmall"}),
                "use_vad": ("BOOLEAN", {"default": True}),
                "use_punctuation": ("BOOLEAN", {"default": True}),
            },
        }

    CATEGORY = "Optional Inputs/FunASR"
    DESCRIPTION = (
        "Transcribe AUDIO into text with per-character timestamps (verbatim "
        "transcript) using FunASR. Requires the optional 'funasr' package "
        "(pip install funasr). Models are downloaded automatically on first "
        "use. A missing (None) audio passes through as missing."
    )

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("text", "chars")
    FUNCTION = "transcribe"

    def transcribe(self, asr_model, use_vad, use_punctuation, audio=None):
        if not has_value(audio):
            return ("", "[]")

        kwargs = {"model": asr_model}
        if use_vad:
            kwargs["vad_model"] = "fsmn-vad"
        if use_punctuation:
            kwargs["punc_model"] = "ct-punc"
        model = _get_model(**kwargs)

        # FunASR reads from a file or a numpy array (float, mono, any rate;
        # its own resampling applies).  Feed the first batch item directly.
        waveform = audio["waveform"]
        import numpy as np

        if waveform.ndim == 3:  # (batch, channels, samples)
            waveform = waveform[0]
        if waveform.ndim == 2:  # (channels, samples) -> mono 1D
            waveform = waveform.mean(dim=0)
        samples = waveform.cpu().numpy().astype(np.float32)

        try:
            results = model.generate(input=samples, fs=audio["sample_rate"])
        except Exception as e:
            raise RuntimeError("FunASR transcription failed: {}".format(e)) from e

        text = ""
        chars = []
        if results:
            first = results[0]
            text = str(first.get("text", "")).strip()
            stamp = first.get("timestamp") or []
            for i, (start_ms, end_ms) in enumerate(stamp):
                chars.append({
                    "index": i,
                    "start": round(start_ms / 1000.0, 3),
                    "end": round(end_ms / 1000.0, 3),
                })
        return (text, json.dumps(chars, ensure_ascii=False))


class VADAutoTrimAudio:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "optional": {
                "audio": ("AUDIO",),
            },
            "required": {
                "padding": ("FLOAT", {"default": 0.2, "min": 0.0, "step": 0.01,
                                      "tooltip": "Seconds of context kept around each detected speech segment"}),
                "min_speech": ("FLOAT", {"default": 0.1, "min": 0.0, "step": 0.01,
                                         "tooltip": "Discard speech segments shorter than this (seconds)"}),
                "merge_gap": ("FLOAT", {"default": 0.4, "min": 0.0, "step": 0.01,
                                        "tooltip": "Merge adjacent speech segments separated by less than this much silence (seconds)"}),
                "vad_model": ("STRING", {"default": "fsmn-vad"}),
            },
        }

    CATEGORY = "Optional Inputs/FunASR"
    DESCRIPTION = (
        "Smart audio trimming: detect speech activity with FunASR's VAD and "
        "cut the silence away. Outputs the trimmed audio, the kept segments "
        "as an editable JSON string ('[[start, end], ...]' in seconds), and "
        "the new total duration. Copy the segments string into Audio Trim "
        "by Segments to hand-edit and re-trim the original audio. Requires "
        "the optional 'funasr' package (pip install funasr)."
    )

    RETURN_TYPES = ("AUDIO", "STRING", "FLOAT")
    RETURN_NAMES = ("audio", "segments", "duration")
    FUNCTION = "trim"

    def trim(self, padding, min_speech, merge_gap, vad_model, audio=None):
        if not has_value(audio):
            return (None, "[]", 0.0)

        model = _get_model(model=vad_model)

        import numpy as np
        waveform = audio["waveform"]
        if waveform.ndim == 3:  # (batch, channels, samples)
            waveform = waveform[0]
        if waveform.ndim == 2:  # (channels, samples) -> mono 1D
            waveform = waveform.mean(dim=0)
        samples = waveform.cpu().numpy().astype(np.float32)

        try:
            results = model.generate(input=samples, fs=audio["sample_rate"])
        except Exception as e:
            raise RuntimeError("FunASR VAD failed: {}".format(e)) from e

        total = _audio_seconds(audio)
        raw_ms = results[0].get("value", []) if results else []
        segments = [[s / 1000.0, e / 1000.0] for s, e in raw_ms]
        segments = [seg for seg in segments if seg[1] - seg[0] >= min_speech]
        segments = _merge_segments(segments, merge_gap)
        padded = [[max(0.0, s - padding), min(total, e + padding)]
                  for s, e in segments]

        trimmed = _slice_audio(audio, padded)
        duration = _audio_seconds(trimmed)
        return (trimmed, _format_segments(padded), duration)


class AudioTrimBySegments:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "optional": {
                "audio": ("AUDIO",),
            },
            "required": {
                "segments": ("STRING", {"default": "[[0.0, 0.0]]", "multiline": True,
                                        "tooltip": "JSON list of [start, end] pairs in seconds. Take VAD Auto Trim's output and edit the numbers, or connect it directly."}),
            },
        }

    CATEGORY = "Optional Inputs/FunASR"
    DESCRIPTION = (
        "Trim audio by an explicit list of [start, end] segments (seconds). "
        "This is the manual second pass for VAD Auto Trim: copy its segments "
        "string, tweak the numbers, and re-trim the original audio. Connect "
        "the string directly for automatic re-trims."
    )

    RETURN_TYPES = ("AUDIO", "FLOAT")
    RETURN_NAMES = ("audio", "duration")
    FUNCTION = "trim"

    def trim(self, segments, audio=None):
        if not has_value(audio):
            return (None, 0.0)
        parsed = _parse_segments(segments)
        trimmed = _slice_audio(audio, parsed)
        return (trimmed, _audio_seconds(trimmed))
