# ComfyUI-Mosael-Plugins

[English](README.md) | [中文](README_zh.md)

Custom nodes that let a **single ComfyUI workflow accept optional inputs** and
automatically switch between execution branches — for example text-to-image vs
image-to-image — **without manual re-wiring, bypassing, muting, or toggling a
boolean switch**.

Drop an image into the loader and the workflow runs img2img. Select `none` and
the same workflow runs txt2img. The unselected branch is **never executed**.

```
Optional Load Image ──image──▶ VAE Encode ──▶ latent_true ──▶ Lazy Latent Switch ──▶ KSampler
        │                                        (skipped when no image)
        └──has_image──▶ condition      Empty Latent ──▶ latent_false ──▶ (selected when no image)
```

## Why stock switches are not enough

A naive approach — a normal switch node, or `IMAGE → VAE Encode` with the
image sometimes missing — fails in two ways:

1. **Eager evaluation.** A regular switch evaluates *both* branches, so
   `VAE Encode` still runs. With no image it receives `None` and crashes; with
   a dummy black image it wastes time encoding garbage.
2. **Dummy images.** Fabricating a 1×1 black image "to keep the graph valid"
   silently changes what the workflow does and violates the principle that a
   black image is *valid data*, not a missing input.

This plugin uses ComfyUI's **officially supported lazy-evaluation protocol**
(`{"lazy": True}` inputs + `check_lazy_status`), so the engine never even
schedules the unselected branch.

## Nodes

| Node | Purpose |
|---|---|
| **Optional Load Image** | Load an image, or explicitly select `none`. Outputs `image` + `mask` (alpha-derived, like the stock Load Image node; both may be `None`) + `has_image`. |
| **Optional Image** | Pass an optional IMAGE connection through, reporting `has_image`. |
| **Has Image** | `IMAGE → BOOLEAN`: is an image present? Decided by identity, never by pixel contents. |
| **Lazy Image Switch** | Pick `image_true` / `image_false` by `condition`; only the selected branch executes. |
| **Lazy Latent Switch** | Same for LATENT (img2img vs txt2img latents). Preserves the full latent dict. |
| **Lazy Any Switch** | Same for any type via the `*` wildcard. No type validation on branches (see below). |

### Missing-value semantics

- Missing input → `image` and `mask` outputs are Python `None`, `has_image` is `False`.
- A valid tensor — **including an all-black or empty-batch image** — is
  present and is passed through unchanged (same object, no copy, batch /
  device / dtype preserved).
- A corrupted or deleted file is a **hard error**, never silently treated as
  "missing".

`None` on an IMAGE output is only safe to feed into lazy switch inputs (or
other nodes that explicitly accept it). This is the platform convention — see
`docs/DESIGN.md` for the full analysis.

## Installation

### ComfyUI Manager (recommended)

Search for "Optional Inputs" in the Manager and install.

### Manual

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/Alndaly/ComfyUI-Mosael-Plugins.git
# restart ComfyUI — no extra Python dependencies required
```

## Usage: one workflow, txt2img *and* img2img

1. Add **Optional Load Image**. Leave it set to `none` for txt2img, or pick /
   upload an image for img2img.
2. Connect it like this:

```
Optional Load Image.image      → VAE Encode.pixels        → Lazy Latent Switch.latent_true
Optional Load Image.has_image  → Lazy Latent Switch.condition
EmptyLatentImage.LATENT        → Lazy Latent Switch.latent_false
Lazy Latent Switch.latent      → KSampler.latent_image
```

3. Run. That's it — no switching, no bypassing.

Ready-made workflows are in [`examples/`](examples/):

- `txt2img_img2img.json` — UI format, load it straight into the ComfyUI canvas.
- `txt2img_img2img_api.json` — API format for `/prompt` submissions.
- `optional_image_basic_api.json` — minimal `Optional Image` / `Has Image` /
  `Lazy Image Switch` demo.

### API usage

The selection is a plain widget value, so the workflow works headlessly:

```python
workflow["4"]["inputs"]["image"] = "none"            # txt2img
workflow["4"]["inputs"]["image"] = "uploaded.png"    # img2img
requests.post("http://127.0.0.1:8188/prompt", json={"prompt": workflow, "client_id": "..."})
```

## How it works

- **Optional inputs.** Inputs declared under `"optional"` may be absent from
  the prompt without failing graph validation.
- **Lazy evaluation.** Branch inputs declared with `{"lazy": True}` are
  excluded from the initial execution graph. The switch's `check_lazy_status`
  requests only the selected branch; the other branch's nodes are never
  scheduled.
- **Caching.** The loader's `IS_CHANGED` hashes the selected file (a stable
  constant for `none`), so adding / removing / replacing an image correctly
  invalidates the cached branch selection — verified by automated tests.
- **Validation.** `VALIDATE_INPUTS` rejects nonexistent files up front (before
  execution), so typos fail fast with a clear message.

Full feasibility analysis, protocol details, and known limitations:
[`docs/DESIGN.md`](docs/DESIGN.md).

## Compatibility

- Tested against **ComfyUI `08ff3c11` / `0df64eb` (master, 2026-10-09)** —
  both the current release line at time of writing.
- Requires no additional Python packages; only ComfyUI core APIs
  (`folder_paths`, `nodes.LoadImage`).
- Legacy (V1) node API, which remains fully supported by the execution engine.

Not yet tested on older ComfyUI versions — if you run one, please open an
issue with the result.

## Testing

Unit tests (no ComfyUI needed):

```bash
pytest tests -m "not integration"
```

Integration tests against a running ComfyUI (with this plugin installed):

```bash
COMFYUI_URL=http://127.0.0.1:8188 pytest tests -m integration
```

The integration suite includes an *always-fail node* placed on the unselected
branch: a passing run is machine proof that lazy execution really skipped it.
For those tests, copy `tests/lazy_proof_pack/` into your `custom_nodes` as
well. Both suites (49 unit + 11 integration tests) pass against ComfyUI
master (2026-10-09) with real checkpoints.

## Troubleshooting

- **"`none` is selected but allow_none is disabled"** — the loader's guard.
  Re-enable `allow_none` or pick an image.
- **"Image file not found … was it deleted"** — the file existed at validation
  time but vanished before execution. Re-select the image.
- **A node crashed receiving `None`** — you connected the optional `image`
  output to a node that requires a real tensor on a path that runs when no
  image exists. Route it through a lazy switch instead.
- **The unselected branch still executes** — some *other* node consumes that
  branch through a non-lazy input, forcing the engine to satisfy it. Give
  that consumer its own input, or check the branch terminates only in the
  switch.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and compatibility reports
on other ComfyUI versions are especially welcome.

## License

[MIT](LICENSE)
