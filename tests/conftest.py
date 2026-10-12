"""Test fixtures.

Unit tests run without a ComfyUI installation: the two ComfyUI modules the
plugin imports at module scope (``folder_paths`` and ``nodes``) are replaced
with lightweight stubs, and the plugin package is loaded exactly the way
ComfyUI loads custom node packages (``spec_from_file_location`` on the
package's ``__init__.py``).

Integration tests (test_workflow_execution.py) talk to a running ComfyUI
server over HTTP and are skipped unless one is reachable.
"""

import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi"}


class StubFolderPaths(types.ModuleType):
    """Minimal stand-in for ComfyUI's folder_paths, rooted at a temp dir."""

    def __init__(self):
        super().__init__("folder_paths")
        self.input_dir = ""

    def get_input_directory(self):
        return self.input_dir

    def filter_files_content_types(self, files, content_types):
        if "image" in content_types:
            return [f for f in files if os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS]
        if "video" in content_types:
            return [f for f in files if os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS]
        return list(files)

    def get_annotated_filepath(self, name, default_dir=None):
        base = os.path.realpath(default_dir or self.input_dir)
        filepath = os.path.abspath(os.path.join(base, name))
        if os.path.commonpath((base, os.path.realpath(filepath))) != base:
            raise ValueError("Invalid file path: {!r}".format(name))
        return filepath

    def exists_annotated_filepath(self, name):
        try:
            filepath = self.get_annotated_filepath(name)
        except ValueError:
            return False
        return os.path.exists(filepath)


class StubLoadImage:
    """Stand-in for nodes.LoadImage whose behaviour tests control directly."""

    # class-level knobs so instances created inside the plugin see them
    result = (object(), object())
    error = None

    def load_image(self, image):
        if StubLoadImage.error is not None:
            raise StubLoadImage.error
        return StubLoadImage.result


class StubNodeOutput:
    """Minimal stand-in for comfy_api io.NodeOutput."""

    def __init__(self, result, ui=None):
        self.result = result
        self.ui = ui


class FakeImageTensor:
    """Minimal tensor stand-in exposing .shape."""

    def __init__(self, shape):
        self.shape = shape


class StubVideoComponents:
    def __init__(self, images=None, audio=None):
        self.images = images if images is not None else FakeImageTensor((4, 64, 64, 3))
        self.audio = audio


class StubVideo:
    """Stand-in for the lazy core Input.Video object."""

    def __init__(self, components=None):
        self.components = components if components is not None else StubVideoComponents()

    def get_components(self):
        return self.components


class StubCoreLoadVideo:
    """Stand-in for comfy_extras.nodes_video.LoadVideo."""

    # class-level knobs
    video = StubVideo()
    decode_error = None
    preview_ui = {"images": [{"filename": "x.mp4"}], "animated": (True,)}
    error = None

    @classmethod
    def execute(cls, file):
        if cls.error is not None:
            raise cls.error
        return StubNodeOutput((cls.video,), cls.preview_ui)


def stub_save_video_preview(video):
    return StubNodeOutput((), {"images": [{"filename": "preview.mp4"}], "animated": (True,)}).ui


def _install_video_stub():
    if "comfy_extras" in sys.modules and "comfy_extras.nodes_video" in sys.modules:
        return
    parent = sys.modules.get("comfy_extras") or types.ModuleType("comfy_extras")
    stub = types.ModuleType("comfy_extras.nodes_video")
    stub.LoadVideo = StubCoreLoadVideo
    stub.save_video_preview = stub_save_video_preview
    sys.modules["comfy_extras"] = parent
    sys.modules["comfy_extras.nodes_video"] = stub
    parent.nodes_video = stub


def _install_stubs():
    if "folder_paths" not in sys.modules:
        sys.modules["folder_paths"] = StubFolderPaths()
    if "nodes" not in sys.modules:
        stub = types.ModuleType("nodes")
        stub.LoadImage = StubLoadImage
        sys.modules["nodes"] = stub
    _install_video_stub()


def _load_plugin():
    if "comfyui_optional_inputs_under_test" in sys.modules:
        return sys.modules["comfyui_optional_inputs_under_test"]
    spec = importlib.util.spec_from_file_location(
        "comfyui_optional_inputs_under_test", PLUGIN_DIR / "__init__.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["comfyui_optional_inputs_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def plugin():
    _install_stubs()
    return _load_plugin()


@pytest.fixture
def input_dir(tmp_path):
    """A fresh input directory exposed to the stubbed folder_paths."""
    directory = tmp_path / "input"
    directory.mkdir()
    sys.modules["folder_paths"].input_dir = str(directory)
    StubLoadImage.result = (object(), object())
    StubLoadImage.error = None
    StubCoreLoadVideo.video = StubVideo()
    StubCoreLoadVideo.preview_ui = {"images": [{"filename": "x.mp4"}], "animated": (True,)}
    StubCoreLoadVideo.error = None
    return directory


@pytest.fixture
def make_image_file(input_dir):
    def _make(name, content=b"fake image bytes"):
        path = input_dir / name
        path.write_bytes(content)
        return name

    return _make
