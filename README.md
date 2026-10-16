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
| **Optional Load Video** | Load a video (same lazy `VIDEO` object as the stock Load Video node), or select `none`. Outputs `video` (may be `None`) + `has_video` + convenience exports `images` (decoded frames), `frame_count`, `audio` — like the stock Get Video Components node. |
| **Optional Load Audio** | Load an audio file (or a video's audio track), or select `none`. Outputs `audio` (may be `None`) + `has_audio` + `sample_rate` + `duration`. |
| **Optional Audio Preview** | Preview audio in the UI. Its `audio` input is lazy and only pulled when `condition` is True — wire `has_audio` in, and the audio branch is skipped entirely when no audio exists. |
| **Quick Audio Edit** | One-node quick editing: trim (start/duration), volume (dB), linear fade-in/fade-out. Optional-safe — a missing audio passes through as missing. Outputs the edited audio and its new duration. |
| **FunASR Transcribe** | Speech-to-text with per-character timestamps (verbatim transcript). Optional dependency: `pip install funasr` (Windows/Linux/macOS). |
| **VAD Auto Trim Audio** | Smart trim: voice-activity detection removes silence. Outputs trimmed audio + an editable segments JSON string. Optional `funasr` dependency. |
| **Audio Trim by Segments** | Manual second pass: edit the segments string (by hand or programmatically) and re-trim the original audio. |
| **LLM API Call** | Call any OpenAI-compatible chat API with a fully custom provider — base URL, API key and model name. Works with OpenAI, DeepSeek, Moonshot, Qwen, SiliconFlow, Groq, OpenRouter, and local Ollama / vLLM / LM Studio. No extra dependencies. |
| **Text Translate** | Translate text with free keyless Google Translate or a custom OpenAI-compatible LLM. Automatic source detection, Google long-text chunking, and LLM terminology/style instructions. No extra dependencies. |
| **Optional Video Preview** | Preview a video in the UI. Its `video` input is lazy and only pulled when `condition` is True — wire `has_video` in, and the video branch is skipped entirely when no video exists. |
| **Optional Image** | Pass an optional IMAGE connection through, reporting `has_image`. |
| **Has Image** | `IMAGE → BOOLEAN`: is an image present? Decided by identity, never by pixel contents. |
| **Lazy Image Switch** | Pick `image_true` / `image_false` by `condition`; only the selected branch executes. |
| **Lazy Latent Switch** | Same for LATENT (img2img vs txt2img latents). Preserves the full latent dict. |
| **Lazy Video Switch** | Same for VIDEO (video-to-video vs generated video). |
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

## Speech-to-text, smart audio trimming, and LLM calls

### FunASR nodes (optional dependency)

`FunASR Transcribe`, `VAD Auto Trim Audio` and `Audio Trim by Segments`
require the optional [FunASR](https://github.com/modelscope/FunASR) package
(not bundled — install it only if you need these nodes):

```bash
pip install funasr
```

Works on Windows, Linux and macOS; models (paraformer-zh, fsmn-vad, …) are
downloaded automatically on first use into the local ModelScope cache. The
nodes register normally either way — without the package they fail at
execution time with the install hint instead of breaking workflow loading.

**Verbatim transcript:** `FunASR Transcribe` outputs the text plus
per-character timestamps (`chars`, JSON: `[{index, start, end}, …]` in
seconds) — ready for subtitles, karaoke timing, or driving effects per
character.

**Smart trim + manual second pass:**

1. `VAD Auto Trim Audio` detects speech and cuts silence away, with
   `padding` / `min_speech` / `merge_gap` controls. It outputs the trimmed
   audio **and** the kept segments as a JSON string like
   `[[0.0, 2.1], [3.2, 5.0]]`.
2. Copy that string into `Audio Trim by Segments`' `segments` widget and
   edit the numbers freely (it tolerates trailing commas, whitespace, and
   `{"start":…, "end":…}` object form), then re-trim the *original* audio —
   or connect the string directly for automatic re-trims.

### LLM API Call

Fully user-defined provider — no vendor list, no hardcoded endpoints:

| Input | Example |
|---|---|
| `base_url` | `https://api.deepseek.com/v1`, `https://api.openai.com/v1`, `http://127.0.0.1:11434/v1` (Ollama) |
| `model` | `deepseek-chat`, `gpt-4o-mini`, `qwen2.5:7b` |
| `api_key` | provider key; leave empty for endpoints that need none (e.g. local Ollama) |

Speaks the OpenAI-compatible `/chat/completions` protocol (OpenAI, DeepSeek,
Moonshot, Qwen, SiliconFlow, Groq, OpenRouter, Ollama, vLLM, LM Studio, …).
Uses only the Python standard library. Note: the API key is a normal widget
value and is saved into the workflow JSON like any input — prefer a
limited/throwaway key.

**JSON output:** set `response_format` to `json_object` to request
guaranteed-JSON replies (the OpenAI-style `response_format` parameter —
supported by OpenAI, DeepSeek, Moonshot, Qwen and others). Mention "json"
and the desired structure in your prompt; some providers reject the
parameter on models that don't support it.

### Text Translate

Add **Text Translate** under `Optional Inputs/LLM`. Connect text (including
`FunASR Transcribe.text`) to `text`; use `translated_text` as the result.

- **Google** (default): keyless, with no extra dependencies. Use
  `source_language=auto` for detection and a target language code such as
  `en`, `zh-CN`, `zh-TW`, `ja`, `ko`, `fr`, or `de`. LLM settings are ignored.
- **LLM**: reuses the existing `LLM API Call` client. Set `base_url`, `model`,
  and `api_key` for any OpenAI-compatible provider. Defaults target local
  Ollama at `http://127.0.0.1:11434/v1`, model `qwen2.5:7b` (must be installed
  or supplied separately). Language names also work. Use `instructions` for
  terminology or style. `max_tokens=0` uses the provider default; increase it
  as needed for long text. The model is instructed to return only a translation.

Example: Chinese prompt → `Text Translate` (Google, auto → en) → `CLIP Text Encode`.
Blank input passes through without a request. Google input is split into chunks
of at most 1000 characters, preferring whitespace boundaries and preserving
boundary whitespace; splitting may reduce context quality. `timeout` applies
per request. Failures raise errors rather than silently returning source text;
an empty LLM translation also raises an error.

Google mode uses an [unofficial Google Translate endpoint](https://github.com/ssut/py-googletrans).
It requires access to `translate.googleapis.com` and may be rate limited or
change without notice; it is separate from the paid
[Google Cloud Translation API](https://cloud.google.com/products/translate/pricing).
LLM API keys are saved in workflow JSON; remove them before sharing.

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
