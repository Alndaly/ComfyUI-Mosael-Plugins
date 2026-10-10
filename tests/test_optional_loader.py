"""Unit tests for the Optional Load Image node (no ComfyUI needed)."""

import hashlib

import pytest

from conftest import StubLoadImage


@pytest.fixture
def cls(plugin):
    return plugin.NODE_CLASS_MAPPINGS["Optional Load Image"]


@pytest.fixture
def node(cls):
    return cls()


def test_input_types_offers_none_first(cls, input_dir, make_image_file):
    make_image_file("a.png")
    make_image_file("b.jpg")
    make_image_file("notes.txt")  # not an image
    types = cls.INPUT_TYPES()
    options = types["required"]["image"][0]
    assert options[0] == "none"
    assert "a.png" in options and "b.jpg" in options
    assert "notes.txt" not in options
    assert options.index("a.png") < options.index("b.jpg")  # sorted
    assert types["required"]["image"][1]["image_upload"] is True
    allow_none = types["required"]["allow_none"]
    assert allow_none[0] == "BOOLEAN"
    assert allow_none[1]["default"] is True


def test_none_selection_needs_no_file(node, input_dir):
    image, has_image = node.load_image("none", True)
    assert image is None
    assert has_image is False


def test_none_selection_with_allow_none_disabled(node, input_dir):
    with pytest.raises(ValueError, match="allow_none"):
        node.load_image("none", False)


def test_image_selection_delegates_to_core_loader(node, input_dir, make_image_file):
    make_image_file("photo.png")
    tensor = object()
    StubLoadImage.result = (tensor, "mask")
    image, has_image = node.load_image("photo.png", True)
    assert image is tensor
    assert has_image is True


def test_missing_file_is_an_error_not_missing(node, input_dir):
    with pytest.raises(FileNotFoundError, match="deleted"):
        node.load_image("ghost.png", True)


def test_deleted_after_validation_is_an_error(node, input_dir, make_image_file):
    name = make_image_file("vanishing.png")
    (input_dir / name).unlink()
    with pytest.raises(FileNotFoundError):
        node.load_image(name, True)


def test_corrupted_image_raises_clear_error(node, input_dir, make_image_file):
    name = make_image_file("broken.png")
    StubLoadImage.error = ValueError("cannot identify image file")
    with pytest.raises(RuntimeError, match=name):
        node.load_image(name, True)


def test_failed_load_is_never_treated_as_missing(node, input_dir, make_image_file):
    name = make_image_file("empty.png")
    StubLoadImage.result = (None, None)  # loader produced nothing
    with pytest.raises(RuntimeError, match="no data"):
        node.load_image(name, True)


def test_validate_inputs(cls, input_dir, make_image_file):
    make_image_file("ok.png")
    assert cls.VALIDATE_INPUTS("none", True) is True
    assert "allow_none" in cls.VALIDATE_INPUTS("none", False)
    assert cls.VALIDATE_INPUTS("ok.png", True) is True
    assert "Invalid image file" in cls.VALIDATE_INPUTS("ghost.png", True)


def test_is_changed_none_is_stable(cls, input_dir):
    assert cls.IS_CHANGED("none", True) == "none"
    assert cls.IS_CHANGED("none", True) == cls.IS_CHANGED("none", False)


def test_is_changed_tracks_file_contents(cls, input_dir, make_image_file):
    name = make_image_file("x.png", b"v1")
    h1 = cls.IS_CHANGED(name, True)
    assert h1 == hashlib.sha256(b"v1").hexdigest()
    make_image_file("x.png", b"v2")
    assert cls.IS_CHANGED(name, True) != h1


def test_is_changed_distinguishes_none_and_file(cls, input_dir, make_image_file):
    name = make_image_file("y.png")
    assert cls.IS_CHANGED(name, True) != cls.IS_CHANGED("none", True)
