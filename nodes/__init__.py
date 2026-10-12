"""Node classes for ComfyUI-Mosael-Plugins."""

from .optional_image import OptionalImage
from .optional_loader import OptionalLoadImage
from .optional_video import OptionalLoadVideo, OptionalVideoPreview
from .presence_detection import HasImage
from .lazy_switch import LazyImageSwitch, LazyLatentSwitch, LazyVideoSwitch, LazyAnySwitch

__all__ = [
    "OptionalImage",
    "OptionalLoadImage",
    "OptionalLoadVideo",
    "OptionalVideoPreview",
    "HasImage",
    "LazyImageSwitch",
    "LazyLatentSwitch",
    "LazyVideoSwitch",
    "LazyAnySwitch",
]
