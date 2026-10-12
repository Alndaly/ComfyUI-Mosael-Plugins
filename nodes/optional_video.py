"""Optional video loading and previewing.

``OptionalLoadVideo`` mirrors ``OptionalLoadImage`` for the core ``VIDEO``
type: pick a video file or explicitly select 'none'.  Loading is delegated
to the core ``LoadVideo`` node so the returned object is the exact same lazy
``Input.Video`` value (file-backed, cheap until components are requested)
and the upload preview UI behaves identically to the stock node.

``OptionalVideoPreview`` previews a video without forcing the video branch
to execute when no video exists: its ``video`` input is lazy and is only
pulled when ``condition`` is True (wire ``has_video`` into it).
"""

import os

import folder_paths

from ..utils.optional_values import NONE_SELECTION, has_value


def _core_video_module():
    # Lazy import: only needed on the "a video is selected" path.  Also keeps
    # unit tests of the 'none' path free of av/torch dependencies.
    from comfy_extras import nodes_video
    return nodes_video


def _ui_as_dict(ui):
    if ui is None:
        return None
    if isinstance(ui, dict):
        return ui
    return ui.as_dict()


class OptionalLoadVideo:
    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
        files = folder_paths.filter_files_content_types(files, ["video"])
        return {
            "required": {
                "video": ([NONE_SELECTION] + sorted(files), {"video_upload": True}),
                "allow_none": ("BOOLEAN", {"default": True}),
            },
        }

    CATEGORY = "Optional Inputs/Video"
    DESCRIPTION = (
        "Load a video from the input directory, or explicitly select 'none'. "
        "Outputs the video (same lazy VIDEO object as the stock Load Video "
        "node) plus a has_video boolean. Selecting 'none' requires no file "
        "and yields a None video output (safe behind lazy switches) with "
        "has_video = False."
    )

    RETURN_TYPES = ("VIDEO", "BOOLEAN")
    RETURN_NAMES = ("video", "has_video")
    FUNCTION = "load_video"

    def load_video(self, video, allow_none):
        if video == NONE_SELECTION:
            if not allow_none:
                raise ValueError(
                    "'none' is selected but allow_none is disabled on Optional Load Video"
                )
            return (None, False)

        if not folder_paths.exists_annotated_filepath(video):
            raise FileNotFoundError(
                "Video file not found: {!r} (was it deleted after the workflow "
                "was validated?)".format(video)
            )

        try:
            node_output = _core_video_module().LoadVideo.execute(video)
        except FileNotFoundError:
            raise
        except Exception as e:
            raise RuntimeError(
                "Failed to load video {!r}: {}".format(video, e)
            ) from e

        loaded = node_output.result[0] if node_output.result else None
        if not has_value(loaded):
            raise RuntimeError(
                "Video loader returned no data for {!r}; refusing to treat a "
                "failed load as a missing video".format(video)
            )

        ui = _ui_as_dict(getattr(node_output, "ui", None))
        if ui is not None:
            return {"ui": ui, "result": (loaded, True)}
        return (loaded, True)

    @classmethod
    def IS_CHANGED(cls, video, allow_none):
        if video == NONE_SELECTION:
            return NONE_SELECTION
        # Mirror the core node: mtime instead of hashing large video files.
        return os.path.getmtime(folder_paths.get_annotated_filepath(video))

    @classmethod
    def VALIDATE_INPUTS(cls, video, allow_none):
        if video == NONE_SELECTION:
            if not allow_none:
                return "'none' is selected but allow_none is disabled"
            return True
        if not folder_paths.exists_annotated_filepath(video):
            return "Invalid video file: {}".format(video)
        return True


class OptionalVideoPreview:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "condition": ("BOOLEAN",),
            },
            "optional": {
                "video": ("VIDEO", {"lazy": True}),
            },
        }

    CATEGORY = "Optional Inputs/Video"
    DESCRIPTION = (
        "Preview a video in the UI without forcing the video branch to run "
        "when no video exists. Wire Optional Load Video's has_video into "
        "condition: when False the video input is never evaluated (an "
        "expensive upstream branch is skipped entirely) and nothing is "
        "previewed. Passes the video through unchanged when present."
    )

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "preview"
    OUTPUT_NODE = True

    def check_lazy_status(self, condition, video=None):
        if condition and video is None:
            return ["video"]
        return []

    def preview(self, condition, video=None):
        if condition and has_value(video):
            ui = _ui_as_dict(_core_video_module().save_video_preview(video))
            return {"ui": ui, "result": (video,)}
        return {"result": (None,)}
