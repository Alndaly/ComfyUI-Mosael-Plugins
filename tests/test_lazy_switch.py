"""Unit tests for the lazy switches.

These test the node-level contract: INPUT_TYPES declarations, the
check_lazy_status truth table, and value pass-through.  End-to-end lazy
execution (the unselected branch never runs) is proven against a live server
in test_workflow_execution.py using an always-fail branch node.
"""

import pytest

SWITCHES = [
    ("Lazy Image Switch", "image_true", "image_false", "IMAGE"),
    ("Lazy Latent Switch", "latent_true", "latent_false", "LATENT"),
    ("Lazy Video Switch", "video_true", "video_false", "VIDEO"),
    ("Lazy Any Switch", "value_true", "value_false", "*"),
]


@pytest.fixture(params=SWITCHES, ids=[s[0] for s in SWITCHES])
def switch(request, plugin):
    name, true_in, false_in, type_name = request.param
    cls = plugin.NODE_CLASS_MAPPINGS[name]
    return cls(), true_in, false_in, type_name


def test_input_types_declares_lazy_branches(switch):
    node, true_in, false_in, type_name = switch
    types = type(node).INPUT_TYPES()
    required = types["required"]
    assert required["condition"][0] == "BOOLEAN"
    assert required[true_in] == (type_name, {"lazy": True})
    assert required[false_in] == (type_name, {"lazy": True})
    cls = type(node)
    assert cls.RETURN_TYPES == (type_name,)


@pytest.mark.parametrize("condition", [True, False])
def test_check_lazy_status_requests_only_selected_branch(switch, condition):
    node, true_in, false_in, _ = switch
    kwargs = {true_in: None, false_in: None}
    needed = node.check_lazy_status(condition, **kwargs)
    if condition:
        assert needed == [true_in]
    else:
        assert needed == [false_in]


@pytest.mark.parametrize("condition", [True, False])
def test_check_lazy_status_requests_nothing_when_resolved(switch, condition):
    node, true_in, false_in, _ = switch
    value = object()
    kwargs = {true_in: value, false_in: value}
    assert node.check_lazy_status(condition, **kwargs) == []


@pytest.mark.parametrize("condition", [True, False])
def test_check_lazy_status_tolerates_legitimate_none(switch, condition):
    # A branch that already evaluated to None must not be re-requested;
    # the executor filters evaluated inputs, and the node must not ask again
    # in a way that would loop (it only asks for the *selected* branch).
    node, true_in, false_in, _ = switch
    selected = true_in if condition else false_in
    unselected = false_in if condition else true_in
    needed = node.check_lazy_status(condition, **{selected: None, unselected: object()})
    assert needed == [selected]


@pytest.mark.parametrize("condition", [True, False])
def test_switch_returns_selected_value_by_identity(switch, condition):
    node, true_in, false_in, _ = switch
    true_value = {"samples": "t", "noise_mask": "keep-me"}
    false_value = {"samples": "f", "batch_index": 7}
    kwargs = {true_in: true_value, false_in: false_value}
    (result,) = node.switch(condition, **kwargs)
    assert result is (true_value if condition else false_value)


def test_latent_structure_preserved(plugin):
    node = plugin.NODE_CLASS_MAPPINGS["Lazy Latent Switch"]()
    latent = {"samples": "s", "noise_mask": "nm", "custom_key": {"deep": 1}}
    (result,) = node.switch(True, latent_true=latent, latent_false=None)
    assert result is latent
    assert result["custom_key"] == {"deep": 1}


def test_any_switch_accepts_plain_values(plugin):
    node = plugin.NODE_CLASS_MAPPINGS["Lazy Any Switch"]()
    assert node.switch(True, value_true=42, value_false="x") == (42,)
    assert node.switch(False, value_true=42, value_false="x") == ("x",)
    assert node.switch(False, value_true=42, value_false=None) == (None,)


def test_all_switches_registered(plugin):
    for name, *_ in SWITCHES:
        assert name in plugin.NODE_CLASS_MAPPINGS
        assert plugin.NODE_DISPLAY_NAME_MAPPINGS[name] == name
