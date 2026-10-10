"""Unit tests for the Optional Image node."""


class FakeTensor:
    """Tensor stand-in — contents must never affect presence decisions."""

    def __init__(self, black=False):
        self.black = black


def test_no_input_connected_is_missing(plugin):
    node = plugin.NODE_CLASS_MAPPINGS["Optional Image"]()
    image, has_image = node.pass_through()
    assert image is None
    assert has_image is False


def test_explicit_none_is_missing(plugin):
    node = plugin.NODE_CLASS_MAPPINGS["Optional Image"]()
    image, has_image = node.pass_through(image=None)
    assert image is None
    assert has_image is False


def test_valid_image_passes_through_by_identity(plugin):
    node = plugin.NODE_CLASS_MAPPINGS["Optional Image"]()
    tensor = FakeTensor()
    image, has_image = node.pass_through(image=tensor)
    assert image is tensor  # no copies
    assert has_image is True


def test_black_image_is_present(plugin):
    # A zero/black image is valid data, not a missing input.
    node = plugin.NODE_CLASS_MAPPINGS["Optional Image"]()
    black = FakeTensor(black=True)
    image, has_image = node.pass_through(image=black)
    assert image is black
    assert has_image is True


def test_input_types_declares_optional_image(plugin):
    types = plugin.NODE_CLASS_MAPPINGS["Optional Image"].INPUT_TYPES()
    assert "image" in types["optional"]
    assert types["optional"]["image"][0] == "IMAGE"
    assert "required" not in types or not types["required"]


def test_return_types(plugin):
    cls = plugin.NODE_CLASS_MAPPINGS["Optional Image"]
    assert cls.RETURN_TYPES == ("IMAGE", "BOOLEAN")
    assert cls.RETURN_NAMES == ("image", "has_image")


def test_has_image_node(plugin):
    cls = plugin.NODE_CLASS_MAPPINGS["Has Image"]
    node = cls()
    assert node.check(image=None) == (False,)
    assert node.check() == (False,)
    tensor = FakeTensor(black=True)
    assert node.check(image=tensor) == (True,)
    assert cls.RETURN_TYPES == ("BOOLEAN",)
