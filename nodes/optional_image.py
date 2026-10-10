"""Optional image input pass-through.

``OptionalImage`` accepts an IMAGE that may be missing and reports whether it
was provided, without ever fabricating a placeholder tensor.
"""

from ..utils.optional_values import has_value


class OptionalImage:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "optional": {
                "image": ("IMAGE",),
            },
        }

    CATEGORY = "Optional Inputs/Image"
    DESCRIPTION = (
        "Accept an optional IMAGE. Passes the image through unchanged and "
        "reports whether an image was provided. When no image is present the "
        "image output is None — connect it to lazy switch inputs "
        "(Lazy Image Switch / Lazy Latent Switch via VAE Encode), which are "
        "the only stock-safe consumers of a missing image."
    )

    RETURN_TYPES = ("IMAGE", "BOOLEAN")
    RETURN_NAMES = ("image", "has_image")
    FUNCTION = "pass_through"

    def pass_through(self, image=None):
        if not has_value(image):
            return (None, False)
        return (image, True)
