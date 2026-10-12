"""Test-only custom nodes for proving lazy execution against a live server.

Copy this folder into your ComfyUI ``custom_nodes`` directory (any folder
name works) and restart the server to enable the tests marked
``@pytest.mark.integration`` in ``test_workflow_execution.py``.

* ``OI Test Fail Image`` / ``OI Test Fail Latent`` / ``OI Test Fail Video`` —
  always raise.  If one of these appears in a workflow run that still
  succeeds, the branch it sits on was provably never executed.
* ``OI Test Constant Image`` / ``OI Test Constant Latent`` — cheap constant
  outputs for the healthy branch.
"""

import torch


class OITestFailImage:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "fail"
    CATEGORY = "Optional Inputs/Testing"

    def fail(self):
        raise RuntimeError("OI_TEST_FAIL: IMAGE branch executed")


class OITestConstantImage:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "constant"
    CATEGORY = "Optional Inputs/Testing"

    def constant(self):
        return (torch.zeros((1, 64, 64, 3)),)


class OITestFailLatent:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    RETURN_TYPES = ("LATENT",)
    FUNCTION = "fail"
    CATEGORY = "Optional Inputs/Testing"

    def fail(self):
        raise RuntimeError("OI_TEST_FAIL: LATENT branch executed")


class OITestConstantLatent:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    RETURN_TYPES = ("LATENT",)
    FUNCTION = "constant"
    CATEGORY = "Optional Inputs/Testing"

    def constant(self):
        return ({"samples": torch.zeros((1, 4, 8, 8))},)


class OITestFailVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    RETURN_TYPES = ("VIDEO",)
    FUNCTION = "fail"
    CATEGORY = "Optional Inputs/Testing"

    def fail(self):
        raise RuntimeError("OI_TEST_FAIL: VIDEO branch executed")


NODE_CLASS_MAPPINGS = {
    "OI Test Fail Image": OITestFailImage,
    "OI Test Constant Image": OITestConstantImage,
    "OI Test Fail Latent": OITestFailLatent,
    "OI Test Constant Latent": OITestConstantLatent,
    "OI Test Fail Video": OITestFailVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "OI Test Fail Image": "OI Test Fail (IMAGE)",
    "OI Test Constant Image": "OI Test Constant (IMAGE)",
    "OI Test Fail Latent": "OI Test Fail (LATENT)",
    "OI Test Constant Latent": "OI Test Constant (LATENT)",
    "OI Test Fail Video": "OI Test Fail (VIDEO)",
}
