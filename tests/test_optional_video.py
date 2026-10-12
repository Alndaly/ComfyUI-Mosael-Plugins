"""Unit tests for the optional video nodes (no ComfyUI needed)."""

import os

import pytest

from conftest import StubCoreLoadVideo, StubVideo, StubVideoComponents, FakeImageTensor


@pytest.fixture
def loader_cls(plugin):
    return plugin.NODE_CLASS_MAPPINGS["Optional Load Video"]


@pytest.fixture
def loader(loader_cls):
    return loader_cls()


@pytest.fixture
def preview_cls(plugin):
    return plugin.NODE_CLASS_MAPPINGS["Optional Video Preview"]


@pytest.fixture
def preview(preview_cls):
    return preview_cls()


def make_video_file(input_dir, name="clip.mp4", content=b"fake video bytes"):
    path = input_dir / name
    path.write_bytes(content)
    return name


# --- Optional Load Video -----------------------------------------------------

def test_input_types_offers_none_first(loader_cls, input_dir):
    make_video_file(input_dir, "a.mp4")
    make_video_file(input_dir, "b.webm")
    make_video_file(input_dir, "notes.txt")  # not a video
    types = loader_cls.INPUT_TYPES()
    options = types["required"]["video"][0]
    assert options[0] == "none"
    assert "a.mp4" in options and "b.webm" in options
    assert "notes.txt" not in options
    assert types["required"]["video"][1]["video_upload"] is True
    assert types["required"]["allow_none"][1]["default"] is True


def test_none_selection_needs_no_file(loader, input_dir):
    video, has_video, images, frame_count, audio = loader.load_video("none", True)
    assert video is None
    assert has_video is False
    assert images is None
    assert frame_count == 0
    assert audio is None


def test_return_types_export_components(loader_cls):
    assert loader_cls.RETURN_TYPES == ("VIDEO", "BOOLEAN", "IMAGE", "INT", "AUDIO")
    assert loader_cls.RETURN_NAMES == ("video", "has_video", "images", "frame_count", "audio")


def test_none_selection_with_allow_none_disabled(loader, input_dir):
    with pytest.raises(ValueError, match="allow_none"):
        loader.load_video("none", False)


def test_video_selection_delegates_to_core_loader(loader, input_dir):
    make_video_file(input_dir, "clip.mp4")
    video_obj = StubVideo(StubVideoComponents(FakeImageTensor((4, 64, 64, 3)), "audio-obj"))
    StubCoreLoadVideo.video = video_obj
    result = loader.load_video("clip.mp4", True)
    # delegates to core and returns dict form carrying the preview UI
    assert isinstance(result, dict)
    assert result["result"] == (video_obj, True, video_obj.components.images, 4, "audio-obj")
    assert result["ui"] == {"images": [{"filename": "x.mp4"}], "animated": (True,)}


def test_frame_count_follows_decoded_images(loader, input_dir):
    make_video_file(input_dir, "long.mp4")
    StubCoreLoadVideo.video = StubVideo(StubVideoComponents(FakeImageTensor((120, 64, 64, 3))))
    result = loader.load_video("long.mp4", True)
    assert result["result"][3] == 120


def test_decode_failure_raises_clear_error(loader, input_dir):
    make_video_file(input_dir, "undecodable.mp4")

    class BrokenVideo:
        def get_components(self):
            raise ValueError("no decoder for codec")

    StubCoreLoadVideo.video = BrokenVideo()
    with pytest.raises(RuntimeError, match="Failed to decode video"):
        loader.load_video("undecodable.mp4", True)


def test_missing_file_is_an_error_not_missing(loader, input_dir):
    with pytest.raises(FileNotFoundError, match="deleted"):
        loader.load_video("ghost.mp4", True)


def test_corrupted_video_raises_clear_error(loader, input_dir):
    make_video_file(input_dir, "broken.mp4")
    StubCoreLoadVideo.error = ValueError("demux failed")
    with pytest.raises(RuntimeError, match="broken.mp4"):
        loader.load_video("broken.mp4", True)


def test_failed_load_is_never_treated_as_missing(loader, input_dir):
    make_video_file(input_dir, "empty.mp4")
    StubCoreLoadVideo.video = None  # core returned no video object
    with pytest.raises(RuntimeError, match="no data"):
        loader.load_video("empty.mp4", True)


def test_validate_inputs(loader_cls, input_dir):
    make_video_file(input_dir, "ok.mp4")
    assert loader_cls.VALIDATE_INPUTS("none", True) is True
    assert "allow_none" in loader_cls.VALIDATE_INPUTS("none", False)
    assert loader_cls.VALIDATE_INPUTS("ok.mp4", True) is True
    assert "Invalid video file" in loader_cls.VALIDATE_INPUTS("ghost.mp4", True)


def test_is_changed_uses_mtime(loader_cls, input_dir):
    name = make_video_file(input_dir, "v.mp4")
    t1 = loader_cls.IS_CHANGED(name, True)
    # same mtime -> stable
    assert loader_cls.IS_CHANGED(name, True) == t1
    # touch the file -> changed
    path = input_dir / name
    st = os.stat(path)
    os.utime(path, (st.st_atime + 10, st.st_mtime + 10))
    assert loader_cls.IS_CHANGED(name, True) != t1


def test_is_changed_none_is_stable(loader_cls, input_dir):
    assert loader_cls.IS_CHANGED("none", True) == "none"


# --- Optional Video Preview --------------------------------------------------

def test_preview_input_types_declares_lazy_optional_video(preview_cls):
    types = preview_cls.INPUT_TYPES()
    assert types["required"]["condition"][0] == "BOOLEAN"
    assert types["optional"]["video"] == ("VIDEO", {"lazy": True})
    assert preview_cls.OUTPUT_NODE is True
    assert preview_cls.RETURN_TYPES == ("VIDEO",)


def test_check_lazy_status_requests_video_only_when_condition_true(preview):
    assert preview.check_lazy_status(True, video=None) == ["video"]
    assert preview.check_lazy_status(False, video=None) == []
    video = object()
    assert preview.check_lazy_status(True, video=video) == []
    assert preview.check_lazy_status(False, video=video) == []


def test_preview_skips_when_condition_false(preview):
    result = preview.preview(False, video=object())
    assert result == {"result": (None,)}


def test_preview_skips_when_condition_true_but_video_none(preview):
    # e.g. upstream evaluated to None (loader set to 'none')
    result = preview.preview(True, video=None)
    assert result == {"result": (None,)}


def test_preview_emits_ui_and_passes_through(preview):
    video = object()
    result = preview.preview(True, video=video)
    assert result["result"] == (video,)
    assert result["ui"]["animated"] == (True,)
    assert result["ui"]["images"]


def test_lazy_video_switch_registered(plugin):
    cls = plugin.NODE_CLASS_MAPPINGS["Lazy Video Switch"]
    types = cls.INPUT_TYPES()
    assert types["required"]["video_true"] == ("VIDEO", {"lazy": True})
    assert types["required"]["video_false"] == ("VIDEO", {"lazy": True})
    assert cls.RETURN_TYPES == ("VIDEO",)
    node = cls()
    assert node.check_lazy_status(True, video_true=None, video_false=object()) == ["video_true"]
    video = object()
    assert node.switch(False, video_true=object(), video_false=video) == (video,)
