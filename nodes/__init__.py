"""Node classes for ComfyUI-Mosael-Plugins."""

from .optional_image import OptionalImage
from .optional_loader import OptionalLoadImage
from .optional_video import OptionalLoadVideo, OptionalVideoPreview
from .optional_audio import OptionalLoadAudio, OptionalAudioPreview, QuickAudioEdit
from .funasr_nodes import FunASRTranscribe, VADAutoTrimAudio, AudioTrimBySegments
from .llm_api import LLMAPICall
from .presence_detection import HasImage
from .lazy_switch import LazyImageSwitch, LazyLatentSwitch, LazyVideoSwitch, LazyAnySwitch

__all__ = [
    "OptionalImage",
    "OptionalLoadImage",
    "OptionalLoadVideo",
    "OptionalVideoPreview",
    "OptionalLoadAudio",
    "OptionalAudioPreview",
    "QuickAudioEdit",
    "FunASRTranscribe",
    "VADAutoTrimAudio",
    "AudioTrimBySegments",
    "LLMAPICall",
    "HasImage",
    "LazyImageSwitch",
    "LazyLatentSwitch",
    "LazyVideoSwitch",
    "LazyAnySwitch",
]
