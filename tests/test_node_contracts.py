"""The legacy node contract used by ComfyUI's object_info and executor."""

import inspect

import pytest

NODE_NAMES = [
    "Optional Image", "Optional Load Image", "Optional Load Video",
    "Optional Video Preview", "Optional Load Audio", "Optional Audio Preview",
    "Quick Audio Edit", "FunASR Transcribe", "VAD Auto Trim Audio",
    "Audio Trim by Segments", "LLM API Call", "Text Translate", "Has Image",
    "Lazy Image Switch", "Lazy Latent Switch", "Lazy Video Switch", "Lazy Any Switch",
]


@pytest.mark.parametrize("name", NODE_NAMES)
def test_registered_node_contract(plugin, input_dir, name):
    cls = plugin.NODE_CLASS_MAPPINGS[name]
    node = cls()
    fields = cls.INPUT_TYPES()
    function = getattr(node, cls.FUNCTION)
    signature = inspect.signature(function)
    accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())
    declared = {key: config for group in ("required", "optional") for key, config in fields.get(group, {}).items()}
    assert set(signature.parameters).issuperset(declared) or accepts_kwargs
    assert len(cls.RETURN_TYPES) == len(cls.RETURN_NAMES)
    assert cls.CATEGORY.startswith("Optional Inputs/")
    assert plugin.NODE_DISPLAY_NAME_MAPPINGS[name]
    for key, config in declared.items():
        assert isinstance(config, tuple) and config
        options = config[1] if len(config) > 1 else {}
        if isinstance(config[0], list):
            assert config[0], "combo must have at least one option"
            if "default" in options:
                assert options["default"] in config[0]
        if "default" in options:
            value = options["default"]
            if "min" in options:
                assert value >= options["min"]
            if "max" in options:
                assert value <= options["max"]
        if options.get("lazy"):
            assert callable(node.check_lazy_status)
    for key in fields.get("optional", {}):
        assert accepts_kwargs or signature.parameters[key].default is not inspect.Parameter.empty
    for key, parameter in signature.parameters.items():
        if parameter.default is inspect.Parameter.empty and parameter.kind not in (
            inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL,
        ):
            assert key in declared
