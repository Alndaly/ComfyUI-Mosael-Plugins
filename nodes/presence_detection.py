"""Presence detection for optional images."""

from ..utils.optional_values import has_value


class HasImage:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "optional": {
                "image": ("IMAGE",),
            },
        }

    CATEGORY = "Optional Inputs/Logic"
    DESCRIPTION = (
        "Report whether an optional IMAGE is present. Presence is decided by "
        "identity (value is not None) — never by pixel contents. A black or "
        "empty-batch image still counts as present."
    )

    RETURN_TYPES = ("BOOLEAN",)
    RETURN_NAMES = ("exists",)
    FUNCTION = "check"

    def check(self, image=None):
        return (has_value(image),)
