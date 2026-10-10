"""Node classes for ComfyUI-Mosael-Plugins."""

from .optional_image import OptionalImage
from .optional_loader import OptionalLoadImage
from .presence_detection import HasImage
from .lazy_switch import LazyImageSwitch, LazyLatentSwitch, LazyAnySwitch

__all__ = [
    "OptionalImage",
    "OptionalLoadImage",
    "HasImage",
    "LazyImageSwitch",
    "LazyLatentSwitch",
    "LazyAnySwitch",
]
