"""Lazy switches: select between two branches without executing the other.

These nodes use ComfyUI's officially supported lazy-evaluation protocol:

* the branch inputs are declared with ``{"lazy": True}``, so the executor does
  not schedule them up front;
* ``check_lazy_status`` is called with the inputs resolved so far (unevaluated
  lazy inputs arrive as ``None``) and returns the names of the inputs that
  still need to be evaluated;
* once everything is resolved, ``FUNCTION`` returns the selected value
  unchanged — by identity, without copies, preserving batch/device/dtype and,
  for LATENT, the complete dict including any additional keys.

The executor filters already-evaluated inputs out of the requested list, so a
branch that legitimately produces ``None`` (e.g. an optional loader with
'none' selected) cannot cause a request loop.
"""


class _LazySwitchBase:
    # Subclasses set:
    #   SWITCH_TYPE      input/output data type string
    #   TRUE_INPUT / FALSE_INPUT / OUTPUT_NAMES  input/output names
    #   DESCRIPTION

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "condition": ("BOOLEAN",),
                cls.TRUE_INPUT: (cls.SWITCH_TYPE, {"lazy": True}),
                cls.FALSE_INPUT: (cls.SWITCH_TYPE, {"lazy": True}),
            },
        }

    CATEGORY = "Optional Inputs/Logic"

    def check_lazy_status(self, condition, **kwargs):
        needed = []
        if condition and kwargs.get(self.TRUE_INPUT) is None:
            needed.append(self.TRUE_INPUT)
        if not condition and kwargs.get(self.FALSE_INPUT) is None:
            needed.append(self.FALSE_INPUT)
        return needed

    def switch(self, condition, **kwargs):
        name = self.TRUE_INPUT if condition else self.FALSE_INPUT
        return (kwargs.get(name),)


class LazyImageSwitch(_LazySwitchBase):
    SWITCH_TYPE = "IMAGE"
    TRUE_INPUT = "image_true"
    FALSE_INPUT = "image_false"

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "switch"
    DESCRIPTION = (
        "Select between two IMAGE inputs. Only the selected branch is "
        "executed; the other branch is never evaluated thanks to lazy inputs."
    )


class LazyLatentSwitch(_LazySwitchBase):
    SWITCH_TYPE = "LATENT"
    TRUE_INPUT = "latent_true"
    FALSE_INPUT = "latent_false"

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("latent",)
    FUNCTION = "switch"
    DESCRIPTION = (
        "Select between two LATENT inputs (e.g. VAE Encode for img2img vs "
        "Empty Latent Image for txt2img). Only the selected branch executes. "
        "The complete latent dict, including additional keys, is preserved."
    )


class LazyAnySwitch(_LazySwitchBase):
    SWITCH_TYPE = "*"
    TRUE_INPUT = "value_true"
    FALSE_INPUT = "value_false"

    RETURN_TYPES = ("*",)
    RETURN_NAMES = ("value",)
    FUNCTION = "switch"
    DESCRIPTION = (
        "Select between two inputs of any type using the '*' wildcard. Only "
        "the selected branch executes. Note: '*' links skip type validation, "
        "so a mismatched selected branch fails at the consumer — prefer the "
        "typed switches when the type is known."
    )
