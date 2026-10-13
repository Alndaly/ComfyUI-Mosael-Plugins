"""Optional audio loading, previewing, and quick editing.

``OptionalLoadAudio`` mirrors the image/video loaders for the core ``AUDIO``
type: pick an audio file (or a video's audio track, like the stock
LoadAudio node) or explicitly select 'none'.  Loading is delegated to the
core ``nodes_audio.load()`` so decoding is identical to the stock node.
Besides the audio object it exports the common components ``sample_rate``
and ``duration``.

``OptionalAudioPreview`` previews audio without forcing the audio branch to
execute when no audio exists: its ``audio`` input is lazy and is only
pulled when ``condition`` is True (wire ``has_audio`` into it).

``QuickAudioEdit`` combines the most common edits — trim, volume, fade in,
fade out — in one node, and is optional-safe: a missing audio passes
through as missing instead of erroring.
"""

import hashlib
import os

import folder_paths

from ..utils.optional_values import NONE_SELECTION, has_value


def _core_audio_module():
    # Lazy import: only needed on the "an audio file is selected" path.
    from comfy_extras import nodes_audio
    return nodes_audio


def _ui_as_dict(ui):
    if ui is None:
        return None
    if isinstance(ui, dict):
        return ui
    return ui.as_dict()


def _audio_duration(audio) -> float:
    if not has_value(audio):
        return 0.0
    return float(audio["waveform"].shape[-1]) / float(audio["sample_rate"])


class OptionalLoadAudio:
    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
        files = folder_paths.filter_files_content_types(files, ["audio", "video"])
        return {
            "required": {
                "audio": ([NONE_SELECTION] + sorted(files), {"audio_upload": True}),
                "allow_none": ("BOOLEAN", {"default": True}),
            },
        }

    CATEGORY = "Optional Inputs/Audio"
    DESCRIPTION = (
        "Load an audio file (or a video's audio track), or explicitly select "
        "'none'. Outputs the audio dict (same structure as the stock Load "
        "Audio node), a has_audio boolean, plus the common components "
        "sample_rate and duration (seconds). Selecting 'none' requires no "
        "file and yields a None audio output with has_audio = False."
    )

    RETURN_TYPES = ("AUDIO", "BOOLEAN", "INT", "FLOAT")
    RETURN_NAMES = ("audio", "has_audio", "sample_rate", "duration")
    FUNCTION = "load_audio"

    def load_audio(self, audio, allow_none):
        if audio == NONE_SELECTION:
            if not allow_none:
                raise ValueError(
                    "'none' is selected but allow_none is disabled on Optional Load Audio"
                )
            return (None, False, 0, 0.0)

        if not folder_paths.exists_annotated_filepath(audio):
            raise FileNotFoundError(
                "Audio file not found: {!r} (was it deleted after the workflow "
                "was validated?)".format(audio)
            )

        try:
            waveform, sample_rate = _core_audio_module().load(
                folder_paths.get_annotated_filepath(audio)
            )
        except FileNotFoundError:
            raise
        except Exception as e:
            raise RuntimeError(
                "Failed to load audio {!r}: {}".format(audio, e)
            ) from e

        if not has_value(waveform):
            raise RuntimeError(
                "Audio loader returned no data for {!r}; refusing to treat a "
                "failed load as a missing audio".format(audio)
            )
        audio_dict = {"waveform": waveform.unsqueeze(0), "sample_rate": sample_rate}
        duration = float(waveform.shape[-1]) / float(sample_rate)
        return (audio_dict, True, int(sample_rate), duration)

    @classmethod
    def IS_CHANGED(cls, audio, allow_none):
        if audio == NONE_SELECTION:
            return NONE_SELECTION
        # Same fingerprint approach as the core LoadAudio node.
        m = hashlib.sha256()
        with open(folder_paths.get_annotated_filepath(audio), "rb") as f:
            m.update(f.read())
        return m.digest().hex()

    @classmethod
    def VALIDATE_INPUTS(cls, audio, allow_none):
        if audio == NONE_SELECTION:
            if not allow_none:
                return "'none' is selected but allow_none is disabled"
            return True
        if not folder_paths.exists_annotated_filepath(audio):
            return "Invalid audio file: {}".format(audio)
        return True


class OptionalAudioPreview:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "condition": ("BOOLEAN",),
            },
            "optional": {
                "audio": ("AUDIO", {"lazy": True}),
            },
        }

    CATEGORY = "Optional Inputs/Audio"
    DESCRIPTION = (
        "Preview audio in the UI without forcing the audio branch to run "
        "when no audio exists. Wire Optional Load Audio's has_audio into "
        "condition: when False the audio input is never evaluated (an "
        "expensive upstream branch is skipped entirely) and nothing is "
        "previewed. Passes the audio through unchanged when present."
    )

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "preview"
    OUTPUT_NODE = True

    def check_lazy_status(self, condition, audio=None):
        if condition and audio is None:
            return ["audio"]
        return []

    def preview(self, condition, audio=None):
        if condition and has_value(audio):
            from comfy_api.latest import ui
            ui_output = ui.PreviewAudio(audio)
            return {"ui": _ui_as_dict(ui_output), "result": (audio,)}
        return {"result": (None,)}


class QuickAudioEdit:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "optional": {
                "audio": ("AUDIO",),
            },
            "required": {
                "start_time": ("FLOAT", {"default": 0.0, "step": 0.01,
                                         "tooltip": "Trim start in seconds; negative counts from the end"}),
                "duration": ("FLOAT", {"default": 0.0, "min": 0.0, "step": 0.01,
                                       "tooltip": "Trim length in seconds; 0 keeps everything to the end"}),
                "volume_db": ("FLOAT", {"default": 0.0, "step": 0.5,
                                        "tooltip": "Volume change in dB; 0 = unchanged, +6 ≈ double, -6 ≈ half"}),
                "fade_in": ("FLOAT", {"default": 0.0, "min": 0.0, "step": 0.01,
                                      "tooltip": "Linear fade-in in seconds"}),
                "fade_out": ("FLOAT", {"default": 0.0, "min": 0.0, "step": 0.01,
                                       "tooltip": "Linear fade-out in seconds"}),
            },
        }

    CATEGORY = "Optional Inputs/Audio"
    DESCRIPTION = (
        "Quick audio editing in one node: trim (start_time/duration), volume "
        "change (dB), linear fade-in and fade-out. A missing (None) audio "
        "input passes through as missing — safe on optional paths behind "
        "lazy switches. Outputs the edited audio and its new duration in "
        "seconds. Edits are applied in trim -> volume -> fade order."
    )

    RETURN_TYPES = ("AUDIO", "FLOAT")
    RETURN_NAMES = ("audio", "duration")
    FUNCTION = "edit"

    def edit(self, start_time, duration, volume_db, fade_in, fade_out, audio=None):
        if not has_value(audio):
            return (None, 0.0)

        waveform = audio["waveform"]
        sample_rate = audio["sample_rate"]
        length = waveform.shape[-1]
        if length == 0:
            return (audio, 0.0)

        # --- trim ---
        if start_time < 0:
            start_frame = length + int(round(start_time * sample_rate))
        else:
            start_frame = int(round(start_time * sample_rate))
        start_frame = max(0, min(start_frame, length))
        if duration > 0:
            end_frame = min(start_frame + int(round(duration * sample_rate)), length)
        else:
            end_frame = length
        waveform = waveform[..., start_frame:end_frame]
        length = waveform.shape[-1]

        # --- volume ---
        if volume_db != 0:
            waveform = waveform * (10 ** (volume_db / 20))

        # --- fades (linear, clamped to the clip length) ---
        fade_in_frames = int(round(fade_in * sample_rate)) if fade_in > 0 else 0
        fade_out_frames = int(round(fade_out * sample_rate)) if fade_out > 0 else 0
        if (fade_in_frames > 0 or fade_out_frames > 0) and length > 1:
            waveform = waveform.clone()
            if fade_in_frames > 0:
                n = min(fade_in_frames, length)
                ramp = torch_linspace(0.0, 1.0, n, device=waveform.device, dtype=waveform.dtype)
                waveform[..., :n] = waveform[..., :n] * ramp
            if fade_out_frames > 0:
                n = min(fade_out_frames, length)
                ramp = torch_linspace(0.0, 1.0, n, device=waveform.device, dtype=waveform.dtype)
                waveform[..., length - n:] = waveform[..., length - n:] * ramp.flip(-1)

        edited = {"waveform": waveform, "sample_rate": sample_rate}
        return (edited, float(length) / float(sample_rate))


def torch_linspace(start, end, steps, device=None, dtype=None):
    # Small helper so the module has no torch import at module scope (keeps
    # the 'none' path import-light for unit tests).
    import torch
    return torch.linspace(start, end, steps, device=device, dtype=dtype)
