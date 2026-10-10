"""ComfyUI-Mosael-Plugins

Custom nodes that let a single workflow accept optional inputs and
automatically switch between execution branches (e.g. text-to-image vs
image-to-image) without manual re-wiring, bypassing, or boolean toggles.

See docs/DESIGN.md for the technical design and README.md for usage.
"""

__version__ = "1.0.0"

from .nodes import (
    OptionalImage,
    OptionalLoadImage,
    HasImage,
    LazyImageSwitch,
    LazyLatentSwitch,
    LazyAnySwitch,
)

NODE_CLASS_MAPPINGS = {
    "Optional Image": OptionalImage,
    "Optional Load Image": OptionalLoadImage,
    "Has Image": HasImage,
    "Lazy Image Switch": LazyImageSwitch,
    "Lazy Latent Switch": LazyLatentSwitch,
    "Lazy Any Switch": LazyAnySwitch,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Optional Image": "Optional Image",
    "Optional Load Image": "Optional Load Image",
    "Has Image": "Has Image",
    "Lazy Image Switch": "Lazy Image Switch",
    "Lazy Latent Switch": "Lazy Latent Switch",
    "Lazy Any Switch": "Lazy Any Switch",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "__version__"]
