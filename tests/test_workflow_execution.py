"""Integration tests against a running ComfyUI server.

Requirements:
* a ComfyUI server with this plugin installed, reachable at
  ``COMFYUI_URL`` (default ``http://127.0.0.1:8188``);
* any checkpoint in ``models/checkpoints``;
* for the lazy-execution proofs, the test pack in ``tests/lazy_proof_pack``
  copied into the server's ``custom_nodes`` directory.

Run with::

    COMFYUI_URL=http://127.0.0.1:8188 pytest -m integration

These tests are skipped automatically when no server is reachable.

How lazy execution is proven (not merely assumed):

1. In the txt2img case the image output is ``None``; if the executor were
   eager, ``VAEEncode`` would receive ``None`` pixels and the run would fail.
   A successful run proves the img2img branch was skipped.
2. With the test pack installed, an always-raising node sits on the
   unselected branch of a lazy switch.  Success proves that branch never ran;
   flipping the condition makes the run fail with that node's message, which
   proves the selection actually follows ``condition``.
"""

import json
import os
from pathlib import Path

import pytest

from comfy_client import ComfyClient, TINY_PNG, TINY_PNG_ALT

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client():
    url = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
    c = ComfyClient(url)
    if not c.reachable():
        pytest.skip("no ComfyUI server reachable at {}".format(url))
    return c


@pytest.fixture(scope="module")
def pack_installed(client):
    try:
        client.object_info("OI Test Fail Image")
        return True
    except Exception:
        return False


def build_workflow(client, image_selection):
    """API-format txt2img/img2img auto-switching workflow (see README)."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": client.first_checkpoint()}},
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "a photo of a cat", "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "ugly, blurry", "clip": ["1", 1]}},
        "4": {"class_type": "Optional Load Image",
              "inputs": {"image": image_selection, "allow_none": True}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": 64, "height": 64, "batch_size": 1}},
        "6": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["4", 0], "vae": ["1", 2]}},
        "7": {"class_type": "Lazy Latent Switch",
              "inputs": {"condition": ["4", 2], "latent_true": ["6", 0], "latent_false": ["5", 0]}},
        "8": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                         "latent_image": ["7", 0], "seed": 42, "steps": 1, "cfg": 1.0,
                         "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["1", 2]}},
        "10": {"class_type": "SaveImage",
               "inputs": {"filename_prefix": "optional_inputs_test", "images": ["9", 0]}},
    }


def test_txt2img_when_no_image(client):
    # VAE Encode would crash on None pixels if the img2img branch ran.
    ok, detail = client.run(build_workflow(client, "none"))
    assert ok, "txt2img run failed: {}".format(detail)


def test_img2img_when_image_uploaded(client):
    name = client.upload_image()
    ok, detail = client.run(build_workflow(client, name))
    assert ok, "img2img run failed: {}".format(detail)


def test_image_replaced(client):
    client.upload_image(content=TINY_PNG, name="oi_replaced_a.png")
    ok, _ = client.run(build_workflow(client, "oi_replaced_a.png"))
    assert ok
    client.upload_image(content=TINY_PNG_ALT, name="oi_replaced_b.png")
    ok, detail = client.run(build_workflow(client, "oi_replaced_b.png"))
    assert ok, "run after replacing image failed: {}".format(detail)


def test_image_removed_after_success(client):
    name = client.upload_image()
    ok, _ = client.run(build_workflow(client, name))
    assert ok
    ok, detail = client.run(build_workflow(client, "none"))
    assert ok, "run after removing image failed: {}".format(detail)


def test_repeated_execution(client):
    workflow = build_workflow(client, "none")
    for _ in range(2):
        ok, detail = client.run(workflow)
        assert ok, detail


def test_serialization_roundtrip(client):
    workflow = json.loads(json.dumps(build_workflow(client, "none")))
    ok, detail = client.run(workflow)
    assert ok, detail


def test_invalid_filename_rejected_by_validation(client):
    _, error = client.queue(build_workflow(client, "ghost_does_not_exist.png"))
    assert error is not None
    body = json.dumps(error)
    assert "ghost_does_not_exist.png" in body


def test_none_with_allow_none_disabled_rejected(client):
    workflow = build_workflow(client, "none")
    workflow["4"]["inputs"]["allow_none"] = False
    _, error = client.queue(workflow)
    assert error is not None
    assert "allow_none" in json.dumps(error)


# --- direct lazy-execution proofs (require the test pack) -------------------

def _lazy_proof_workflow(constant_node, fail_node, condition):
    return {
        "1": {"class_type": constant_node, "inputs": {}},
        "2": {"class_type": fail_node, "inputs": {}},
        "3": {"class_type": "Lazy Image Switch",
              "inputs": {"condition": condition, "image_true": ["1", 0], "image_false": ["2", 0]}},
        "4": {"class_type": "SaveImage",
              "inputs": {"filename_prefix": "oi_lazy_proof", "images": ["3", 0]}},
    }


def test_lazy_image_switch_skips_unselected_branch(client, pack_installed):
    if not pack_installed:
        pytest.skip("lazy_proof_pack not installed on the server")
    workflow = _lazy_proof_workflow("OI Test Constant Image", "OI Test Fail Image", True)
    ok, detail = client.run(workflow)
    assert ok, "unselected IMAGE branch was executed: {}".format(detail)


def test_lazy_image_switch_executes_selected_branch(client, pack_installed):
    if not pack_installed:
        pytest.skip("lazy_proof_pack not installed on the server")
    workflow = _lazy_proof_workflow("OI Test Constant Image", "OI Test Fail Image", False)
    ok, detail = client.run(workflow)
    assert not ok
    assert "OI_TEST_FAIL" in detail


def test_lazy_latent_switch_skips_unselected_branch(client, pack_installed):
    if not pack_installed:
        pytest.skip("lazy_proof_pack not installed on the server")
    # latent_true <- constant latent, latent_false <- failing latent
    workflow = {
        "1": {"class_type": "OI Test Constant Latent", "inputs": {}},
        "2": {"class_type": "OI Test Fail Latent", "inputs": {}},
        "3": {"class_type": "Lazy Latent Switch",
              "inputs": {"condition": True, "latent_true": ["1", 0], "latent_false": ["2", 0]}},
        "4": {"class_type": "VAEDecode",
              "inputs": {"samples": ["3", 0], "vae": ["5", 2]}},
        "5": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": client.first_checkpoint()}},
        "6": {"class_type": "SaveImage",
              "inputs": {"filename_prefix": "oi_lazy_proof", "images": ["4", 0]}},
    }
    ok, detail = client.run(workflow)
    assert ok, "unselected LATENT branch was executed: {}".format(detail)


# --- optional video nodes ----------------------------------------------------

TINY_MP4_PATH = Path(__file__).parent / "tiny_video.mp4"


def _upload_video(client):
    return client.upload_image(
        content=TINY_MP4_PATH.read_bytes(), name="oi_test_video.mp4"
    )


def _video_workflow(client, selection):
    return {
        "1": {"class_type": "Optional Load Video",
              "inputs": {"video": selection, "allow_none": True}},
        "2": {"class_type": "Optional Video Preview",
              "inputs": {"condition": ["1", 1], "video": ["1", 0]}},
    }


def test_optional_video_none(client):
    # has_video = False -> the preview never pulls the video output; the
    # workflow still completes with the preview node as its only output node.
    ok, detail = client.run(_video_workflow(client, "none"))
    assert ok, "video-less run failed: {}".format(detail)


def test_optional_video_with_file(client):
    name = _upload_video(client)
    ok, detail = client.run(_video_workflow(client, name))
    assert ok, "video run failed: {}".format(detail)


def test_optional_video_invalid_file_rejected(client):
    _, error = client.queue(_video_workflow(client, "ghost_video.mp4"))
    assert error is not None
    assert "ghost_video.mp4" in json.dumps(error)


def test_optional_video_preview_skips_branch_without_video(client):
    # VideoSlice would crash on a None video; the lazy preview must never
    # pull the video branch when has_video is False.  A successful run
    # proves VideoSlice was not executed.
    workflow = {
        "1": {"class_type": "Optional Load Video",
              "inputs": {"video": "none", "allow_none": True}},
        "2": {"class_type": "Video Slice",
              "inputs": {"video": ["1", 0], "start_time": 0.0, "duration": 0.0,
                         "strict_duration": False}},
        "3": {"class_type": "Optional Video Preview",
              "inputs": {"condition": ["1", 1], "video": ["2", 0]}},
    }
    ok, detail = client.run(workflow)
    assert ok, "video branch was executed despite has_video=False: {}".format(detail)


def test_lazy_video_switch_skips_unselected_branch(client, pack_installed):
    if not pack_installed:
        pytest.skip("lazy_proof_pack not installed on the server")
    # Constant video from a file on the true branch, failing node on false.
    name = _upload_video(client)
    workflow = {
        "1": {"class_type": "Optional Load Video",
              "inputs": {"video": name, "allow_none": True}},
        "2": {"class_type": "OI Test Fail Video", "inputs": {}},
        "3": {"class_type": "Lazy Video Switch",
              "inputs": {"condition": True, "video_true": ["1", 0], "video_false": ["2", 0]}},
        "4": {"class_type": "Optional Video Preview",
              "inputs": {"condition": True, "video": ["3", 0]}},
    }
    ok, detail = client.run(workflow)
    assert ok, "unselected VIDEO branch was executed: {}".format(detail)


def test_lazy_video_switch_executes_selected_branch(client, pack_installed):
    if not pack_installed:
        pytest.skip("lazy_proof_pack not installed on the server")
    workflow = {
        "1": {"class_type": "Optional Load Video",
              "inputs": {"video": "none", "allow_none": True}},
        "2": {"class_type": "OI Test Fail Video", "inputs": {}},
        "3": {"class_type": "Lazy Video Switch",
              "inputs": {"condition": False, "video_true": ["1", 0], "video_false": ["2", 0]}},
        "4": {"class_type": "Optional Video Preview",
              "inputs": {"condition": True, "video": ["3", 0]}},
    }
    ok, detail = client.run(workflow)
    assert not ok
    assert "OI_TEST_FAIL" in detail
