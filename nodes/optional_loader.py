"""Image loader with an explicit "none" selection.

``OptionalLoadImage`` behaves like the stock ``LoadImage`` node but lets the
user pick "none" (or leave the workflow image-less via the API).  Image
decoding is delegated to the core node so that format support, EXIF
orientation, alpha handling and dtype/device placement stay identical to
ComfyUI's own loader.
"""

import hashlib
import os

import folder_paths
import nodes as comfy_nodes

from ..utils.optional_values import NONE_SELECTION, has_value


class OptionalLoadImage:
    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
        files = folder_paths.filter_files_content_types(files, ["image"])
        return {
            "required": {
                "image": ([NONE_SELECTION] + sorted(files), {"image_upload": True}),
                "allow_none": ("BOOLEAN", {"default": True}),
            },
        }

    CATEGORY = "Optional Inputs/Image"
    DESCRIPTION = (
        "Load an image from the input directory, or explicitly select 'none'. "
        "Outputs image, mask (alpha-derived, like the stock Load Image node) "
        "and a has_image boolean. Selecting 'none' requires no image file and "
        "yields None image/mask outputs (safe behind lazy switches) with "
        "has_image = False."
    )

    RETURN_TYPES = ("IMAGE", "MASK", "BOOLEAN")
    RETURN_NAMES = ("image", "mask", "has_image")
    FUNCTION = "load_image"

    def load_image(self, image, allow_none):
        if image == NONE_SELECTION:
            if not allow_none:
                # VALIDATE_INPUTS normally catches this; keep a runtime guard
                # for API calls that skip validation.
                raise ValueError(
                    "'none' is selected but allow_none is disabled on Optional Load Image"
                )
            return (None, None, False)

        if not folder_paths.exists_annotated_filepath(image):
            # A file that existed at validation time may have been deleted
            # before execution.  This is an error, never a silent "missing".
            raise FileNotFoundError(
                "Image file not found: {!r} (was it deleted after the workflow "
                "was validated?)".format(image)
            )

        try:
            # Delegate to the core loader for full format/EXIF/alpha support.
            # It returns (image, mask), where the mask is alpha-derived and is
            # a zero tensor for images without an alpha channel — identical to
            # the stock Load Image node.
            tensor, mask = comfy_nodes.LoadImage().load_image(image)
        except FileNotFoundError:
            raise
        except Exception as e:
            raise RuntimeError(
                "Failed to load image {!r}: {}".format(image, e)
            ) from e

        if not has_value(tensor):
            raise RuntimeError(
                "Image loader returned no data for {!r}; refusing to treat a "
                "failed load as a missing image".format(image)
            )
        return (tensor, mask, True)

    @classmethod
    def IS_CHANGED(cls, image, allow_none):
        if image == NONE_SELECTION:
            # Stable constant: switching none -> file (or back) still changes
            # the value and correctly invalidates the cache.
            return NONE_SELECTION
        with open(folder_paths.get_annotated_filepath(image), "rb") as f:
            m = hashlib.sha256()
            m.update(f.read())
        return m.digest().hex()

    @classmethod
    def VALIDATE_INPUTS(cls, image, allow_none):
        if image == NONE_SELECTION:
            if not allow_none:
                return "'none' is selected but allow_none is disabled"
            return True
        if not folder_paths.exists_annotated_filepath(image):
            return "Invalid image file: {}".format(image)
        return True
