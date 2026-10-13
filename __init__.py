"""ComfyUI-Mosael-Plugins

Custom nodes that let a single workflow accept optional inputs and
automatically switch between execution branches (e.g. text-to-image vs
image-to-image) without manual re-wiring, bypassing, or boolean toggles.

See docs/DESIGN.md for the technical design and README.md for usage.
"""

__version__ = "1.5.0"

from .nodes import (
    OptionalImage,
    OptionalLoadImage,
    OptionalLoadVideo,
    OptionalVideoPreview,
    OptionalLoadAudio,
    OptionalAudioPreview,
    QuickAudioEdit,
    FunASRTranscribe,
    VADAutoTrimAudio,
    AudioTrimBySegments,
    LLMAPICall,
    HasImage,
    LazyImageSwitch,
    LazyLatentSwitch,
    LazyVideoSwitch,
    LazyAnySwitch,
)

NODE_CLASS_MAPPINGS = {
    "Optional Image": OptionalImage,
    "Optional Load Image": OptionalLoadImage,
    "Optional Load Video": OptionalLoadVideo,
    "Optional Video Preview": OptionalVideoPreview,
    "Optional Load Audio": OptionalLoadAudio,
    "Optional Audio Preview": OptionalAudioPreview,
    "Quick Audio Edit": QuickAudioEdit,
    "FunASR Transcribe": FunASRTranscribe,
    "VAD Auto Trim Audio": VADAutoTrimAudio,
    "Audio Trim by Segments": AudioTrimBySegments,
    "LLM API Call": LLMAPICall,
    "Has Image": HasImage,
    "Lazy Image Switch": LazyImageSwitch,
    "Lazy Latent Switch": LazyLatentSwitch,
    "Lazy Video Switch": LazyVideoSwitch,
    "Lazy Any Switch": LazyAnySwitch,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Optional Image": "Optional Image",
    "Optional Load Image": "Optional Load Image",
    "Optional Load Video": "Optional Load Video",
    "Optional Video Preview": "Optional Video Preview",
    "Optional Load Audio": "Optional Load Audio",
    "Optional Audio Preview": "Optional Audio Preview",
    "Quick Audio Edit": "Quick Audio Edit",
    "FunASR Transcribe": "FunASR Transcribe",
    "VAD Auto Trim Audio": "VAD Auto Trim Audio",
    "Audio Trim by Segments": "Audio Trim by Segments",
    "LLM API Call": "LLM API Call",
    "Has Image": "Has Image",
    "Lazy Image Switch": "Lazy Image Switch",
    "Lazy Latent Switch": "Lazy Latent Switch",
    "Lazy Video Switch": "Lazy Video Switch",
    "Lazy Any Switch": "Lazy Any Switch",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "__version__"]
