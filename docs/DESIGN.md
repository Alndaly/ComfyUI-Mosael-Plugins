# Technical Design — ComfyUI-Mosael-Plugins

This document records the feasibility assessment and architecture of the plugin.
Every mechanism described here was verified against the ComfyUI source at commit
`0df64eb` (master, 2026-10-09). File references point into the ComfyUI
repository.

## 1. Feasibility assessment (summary)

**The plugin is fully feasible with officially supported mechanisms only.** No
core modification, no undocumented hacks, and no frontend JavaScript are
required. The three pillars:

1. **Optional inputs** are a first-class concept: inputs declared under the
   `"optional"` key of `INPUT_TYPES()` may be absent from the prompt without
   triggering validation errors (`comfy_execution/validation.py`,
   `validate_inputs()`: only `"required"` inputs produce
   `required_input_missing`).
2. **Lazy evaluation** is officially supported for legacy-style nodes: an input
   declared with `{"lazy": True}` is excluded from the initial dependency graph
   (`comfy_execution/graph.py`, `TopologicalSort.add_node()`), and the node's
   `check_lazy_status()` method tells the executor which lazy inputs still need
   to be evaluated (`execution.py`, `execute()`). The built-in `SwitchNode` in
   `comfy_extras/nodes_logic.py` and the `TestLazyMixImages` node in
   `tests/execution/testing_nodes/testing-pack/specific_tests.py` are the
   reference implementations of this exact pattern.
3. **`None` is a valid runtime value on any output.** The executor and the
   caches store and forward `None` outputs without complaint; graph validation
   is purely type-string based and never inspects values. The built-in
   `SwitchNode` deliberately returns `None` for unconnected optional outputs.

Known limitations are listed in section 8.

## 2. Missing-value representation

### Decision

A missing image is represented by **Python `None`** on the data output, paired
with a **`BOOLEAN` presence output** (`has_image` / `exists`).

### Why `None` and not a dummy tensor or a custom sentinel

- The engine passes `None` outputs through links normally
  (`execution.py: get_output_data()` → `CacheEntry(outputs=[None])` →
  downstream `get_input_data()` passes `None`). A custom sentinel object would
  be indistinguishable from a valid tensor to any non-plugin node.
- Validation compares only type strings (`RETURN_TYPES` vs. the input type),
  so a `None` IMAGE output never fails graph validation.
- ComfyUI's own lazy convention uses `None` as the "connected but not yet
  evaluated" placeholder (`execution.py: get_input_data()` marks unevaluated
  lazy inputs as `(None,)`). Using `None` as "no value" aligns with the
  platform instead of fighting it.
- The spec forbids dummy black images; we never fabricate tensors.

### State semantics

| State | Runtime representation | Result |
|---|---|---|
| Input not connected | kwarg absent / default `None` | `has_image = False`, image output `None` |
| Upstream explicitly produced no value | value is `None` | same as above — *intentionally unified* |
| Valid value (including all-black / empty-batch tensors) | value is not `None` | `has_image = True`, value passed through unchanged |
| Invalid value (corrupted file, deleted file) | loader raises | hard error — never treated as missing |

Presence detection is strictly `value is not None`; pixel contents are never
inspected. Because the two "absent" states collapse into one runtime state,
`Optional Image` cannot distinguish "not wired" from "wired to a producer that
yielded nothing" — and does not need to: both mean "no image" for every
downstream decision. (Inside `check_lazy_status()`, "not yet evaluated" vs.
"evaluated to `None`" *is* distinguishable by the executor, which filters
already-evaluated inputs out of the requested list — see section 4.)

## 3. Node inventory

| Class | Node id | Category | Data type |
|---|---|---|---|
| `OptionalImage` | `Optional Image` | Optional Inputs/Image | IMAGE |
| `OptionalLoadImage` | `Optional Load Image` | Optional Inputs/Image | IMAGE, MASK || `OptionalLoadVideo` | `Optional Load Video` | Optional Inputs/Video | VIDEO, BOOLEAN, IMAGE, INT, AUDIO |
| `OptionalVideoPreview` | `Optional Video Preview` | Optional Inputs/Video | VIDEO |
| `OptionalLoadAudio` | `Optional Load Audio` | Optional Inputs/Audio | AUDIO, BOOLEAN, INT, FLOAT |
| `OptionalAudioPreview` | `Optional Audio Preview` | Optional Inputs/Audio | AUDIO |
| `QuickAudioEdit` | `Quick Audio Edit` | Optional Inputs/Audio | AUDIO, FLOAT |
| `FunASRTranscribe` | `FunASR Transcribe` | Optional Inputs/FunASR | STRING, STRING |
| `VADAutoTrimAudio` | `VAD Auto Trim Audio` | Optional Inputs/FunASR | AUDIO, STRING, FLOAT |
| `AudioTrimBySegments` | `Audio Trim by Segments` | Optional Inputs/FunASR | AUDIO, FLOAT |
| `LLMAPICall` | `LLM API Call` | Optional Inputs/LLM | STRING |
| `HasImage` | `Has Image` | Optional Inputs/Logic | IMAGE → BOOLEAN |
| `LazyImageSwitch` | `Lazy Image Switch` | Optional Inputs/Logic | IMAGE |
| `LazyLatentSwitch` | `Lazy Latent Switch` | Optional Inputs/Logic | LATENT |
| `LazyVideoSwitch` | `Lazy Video Switch` | Optional Inputs/Logic | VIDEO |
| `LazyAnySwitch` | `Lazy Any Switch` | Optional Inputs/Logic | `*` |

All nodes use the **legacy (V1) custom node API** (`INPUT_TYPES` /
`RETURN_TYPES` / `FUNCTION` class attributes). The newer V3 `io.ComfyNode` API
is still marked experimental in core for some node types and is not needed
here; the legacy API remains fully supported (`execution.py` dispatches on
`issubclass(class_def, _ComfyNodeInternal)`).

## 4. Lazy switch protocol

Declared inputs (`lazy_switch.py`):

```python
"required": {
    "condition": ("BOOLEAN",),
    "image_true":  ("IMAGE", {"lazy": True}),
    "image_false": ("IMAGE", {"lazy": True}),
}
```

`check_lazy_status(condition, image_true=None, image_false=None)` returns the
list of input names that must still be evaluated:

```python
needed = []
if condition and image_true is None:
    needed.append("image_true")
if not condition and image_false is None:
    needed.append("image_false")
return needed
```

Executor behavior (verified in `execution.py: execute()`):

1. `condition` is a non-lazy input, so it is evaluated before the switch can
   run.
2. Lazy links are excluded from the initial topological sort, so the branch
   that is not requested is **never scheduled** — its nodes are not executed.
3. `check_lazy_status()` is invoked with the inputs resolved so far; unevaluated
   lazy inputs arrive as `None` (and are recorded in `missing_keys`).
4. If the returned names are not yet in `input_data_all` (or are in
   `missing_keys`), the engine converts them into strong links and re-stages
   the node. Already-evaluated inputs are filtered out, so a branch that
   legitimately produced `None` cannot cause an infinite request loop.
5. When nothing more is needed, `FUNCTION` runs and returns the selected value
   unchanged (no copies; LATENT dicts, tensors, and any custom object are
   passed through by identity).

### Why this prevents the `VAE Encode(None)` crash

In the reference workflow, `Optional Load Image.image → VAE Encode →
LazyLatentSwitch.latent_true` and `has_image → condition`. When no image is
selected, the switch's `check_lazy_status` requests only `latent_false`, so
`VAE Encode` never enters the execution list and its `pixels=None` input never
crashes. When an image is present, `latent_true` is requested and `VAE Encode`
runs with a real tensor. This is the officially recommended pattern; the
`ExecutionBlocker` mechanism is deliberately *not* used (it is reserved for
conditionally blocking output nodes, per its own docstring in
`comfy_execution/graph_utils.py`).

## 5. Optional Load Image

- **Inputs**: `image` — combo of `["none"] + input-directory images` with the
  native `{"image_upload": True}` option so the stock upload button and image
  preview appear without any frontend JavaScript; `allow_none` — BOOLEAN,
  default `True`.
- **Outputs**: `(image, mask, has_image)`. The mask is the alpha-derived
  tensor from the core loader (a zero tensor for images without alpha), same
  as the stock `LoadImage` node; it is `None` together with `image` when
  `none` is selected.
- **Selection `"none"`** → `(None, False)` without touching the filesystem.
- **Loading** delegates to the core `nodes.LoadImage().load_image()`, which
  inherits full core behavior: PNG/JPEG/WebP (including animated WebP),
  EXIF-orientation, alpha masks, dtype/device placement, and the annotated
  filepath (`[filename]`, `[subdirectory]`) conventions.
- **`IS_CHANGED(image, allow_none)`** mirrors the core node: returns the
  SHA-256 of the file (contents change → re-execute) or the constant
  `"none"`.
- **`VALIDATE_INPUTS(image, allow_none)`**: returns an error string for a
  nonexistent/deleted file or for `"none"` while `allow_none` is disabled;
  declares both widget names so the generic combo-membership check (which uses
  a possibly stale file listing) is skipped for them — the same technique the
  core `LoadImage` uses.
- **Runtime safety**: the annotated-filepath resolver in `folder_paths.py`
  performs path-containment checks, so crafted filenames cannot escape the
  input directory.

### API execution

Everything above is server-side. The combo value `"none"` is a plain string,
so `/prompt` submissions work with the image selected, with `"none"`, and with
a programmatically updated filename. No frontend state is involved.

## 5b. Optional video nodes

Modern ComfyUI ships a `VIDEO` type (`io.Video`, io_type `"VIDEO"`) whose
values are lazy, file-backed `Input.Video` objects (`comfy_extras/
nodes_video.py`). The plugin mirrors the image design for it:

- **`OptionalLoadVideo`** offers `["none"] + video files` with the native
  `{"video_upload": True}` widget and delegates to the core `LoadVideo.
  execute()`, returning the exact same lazy video object plus the stock
  upload-preview UI. `IS_CHANGED` uses the file mtime — like the core
  node's `fingerprint_inputs` — instead of hashing large videos. The
  `comfy_extras.nodes_video` import is deferred to the "a video is
  selected" path, so the `none` path (and its unit tests) stays free of
  av/torch imports. It additionally exports the decoded components —
  `images`, `frame_count`, `audio` — via one `get_components()` call, so a
  single loader also covers frame-based workflows (the role of the stock
  `GetVideoComponents` node). The `video`/`has_video` slots keep their
  indices; the new exports are appended after them, so existing links are
  unaffected.
- **`OptionalVideoPreview`** is an output node with a lazy optional `video`
  input and a required `condition` BOOLEAN. `check_lazy_status` requests
  the video only when `condition` is True, so wiring `has_video` into
  `condition` guarantees the entire video branch (including intermediate
  processing nodes that would crash on `None`) is skipped when no video
  exists. When a video is present it is encoded to a temp MP4 via the
  core `save_video_preview` helper and emitted as `PreviewVideo` UI,
  passing the video through unchanged.
- **`LazyVideoSwitch`** is the typed VIDEO sibling of the image/latent
  switches; identical protocol.

## 5c. Optional audio nodes

The core `AUDIO` type is a dict `{"waveform": Tensor[batch, channels,
samples], "sample_rate": int}` (`comfy_api/latest/_io.py`). The plugin
mirrors the image/video design:

- **`OptionalLoadAudio`** offers `["none"] + audio and video files` (the
  stock `LoadAudio` also accepts video containers for their audio track)
  with the native `{"audio_upload": True}` widget. Decoding delegates to
  the core `nodes_audio.load()`, and the audio dict is built exactly like
  the stock node's (`waveform.unsqueeze(0)` for the batch dimension).
  Common components are exported directly: `sample_rate` (INT) and
  `duration` in seconds (FLOAT). `IS_CHANGED` hashes the file like the
  core node's `fingerprint_inputs` (audio files are small enough).
- **`OptionalAudioPreview`** follows the `OptionalVideoPreview` pattern:
  lazy optional `audio` pulled only when `condition` is True, then
  previewed through the core `ui.PreviewAudio` helper (which encodes a
  temp FLAC) and passed through unchanged.
- **`QuickAudioEdit`** bundles the most frequent edits in one node —
  trim (`start_time` seconds, negative counts from the end; `duration`
  0 = to the end, mirroring the core `TrimAudioDuration` semantics),
  volume (`volume_db`, `10**(dB/20)` linear gain like the core
  `AudioAdjustVolume`), and linear fade-in/fade-out clamped to the clip
  length. Edits apply as trim → volume → fades; a `None` input passes
  through as `None`, making the node safe anywhere on an optional path.
  It outputs the edited audio plus its new `duration` (FLOAT seconds).

## 6. Validation analysis

- Missing optional inputs: no error (only `required` inputs are enforced).
- Type checking of links: `validate_node_input()` in
  `comfy_execution/validation.py` compares type strings and explicitly
  supports `"*"` (Any) on either side, comma-unions, and `MatchType`. Our
  typed switches produce strictly typed links; `Lazy Any Switch` uses the
  officially recognized `"*"` wildcard.
- Validation walks *all* links, including lazy ones, so `VAE Encode` is
  type-checked (and its required inputs verified) even in the run where it
  will not execute. A workflow that passes validation therefore also passes
  runtime.
- `Lazy Any Switch` tradeoff: `"*"` links are exempt from type checking by
  design. Branches of differing concrete types are accepted at validation and
  fail only at the consumer if the *selected* branch's type is incompatible.
  The typed switches exist precisely for users who want validation coverage.

## 7. Caching analysis

ComfyUI caches outputs keyed by an input signature (`CacheKeySetInputSignature`
in `comfy_execution/caching.py`): a node re-executes when its widgets, its
`IS_CHANGED` result, or any ancestor's signature changes.

| Scenario | Behavior |
|---|---|
| No image, re-run | loader `IS_CHANGED` = `"none"` (stable) → whole graph cache-hits |
| Image added | loader `IS_CHANGED` changes → loader re-executes → `has_image` flips → switch signature changes → re-executes, requests `latent_true` → `VAE Encode` re-executes |
| Image removed | same invalidation chain in reverse; `VAE Encode` is simply not scheduled |
| Image replaced | file hash changes → same as "added" |
| File contents edited | hash changes → re-execute |
| Repeated execution | all pure functions; no `NOT_IDEMPOTENT` needed |

There is no path where a stale `has_image` survives a change to the image
selection, because the presence boolean is recomputed whenever the loader
re-executes, and the loader re-executes whenever its signature changes.

## 8. Known limitations

1. **Shared consumers.** If a node on the "unused" branch also feeds a
   *non-lazy* input of some other node, that consumer will pull the branch
   into execution (the engine must satisfy its dependency). In the txt2img /
   img2img workflow the img2img branch must terminate only in the switch's
   lazy input. This is inherent to lazy evaluation, not a bug.
2. **`None` is only safe on lazy paths.** Connecting the `image` output of
   `Optional Image` / `Optional Load Image` to a stock node that requires a
   real IMAGE tensor is only valid when the image exists; when it is `None`,
   such a link must be (transitively) behind one of the lazy switches.
   Documented in the README.
3. **Wildcard typing.** `Lazy Any Switch` cannot validate branch types; use
   the typed switches when the data type is known.
4. **"Not connected" vs. "explicitly none"** are intentionally unified at the
   data level (see section 2). The boolean outputs carry the only presence
   information that matters downstream.
5. **Frontend widget ordering.** Example workflows pin the widget-value layout
   of current built-in nodes; a future ComfyUI that reorders widgets may
   require re-saving the examples. The API-format example is immune.

## 9. Project structure

```
ComfyUI-Mosael-Plugins/
├── __init__.py              # exports NODE_CLASS_MAPPINGS / NODE_DISPLAY_NAME_MAPPINGS
├── pyproject.toml
├── nodes/
│   ├── optional_image.py    # OptionalImage
│   ├── optional_loader.py   # OptionalLoadImage
│   ├── presence_detection.py# HasImage
│   └── lazy_switch.py       # LazyImageSwitch / LazyLatentSwitch / LazyAnySwitch
├── utils/
│   └── optional_values.py   # "none" selection constant + presence helpers
├── examples/                # UI-format + API-format workflows
├── tests/                   # unit tests (no ComfyUI needed) + live-server integration tests
│   └── counter_pack/        # tiny test-only custom node pack for lazy-execution proof
└── docs/
    └── DESIGN.md            # this document
```

### Testing strategy

- **Unit tests** (run anywhere, no torch/ComfyUI): node logic, presence
  semantics, `check_lazy_status` truth tables, loader validation/`IS_CHANGED`,
  error handling. ComfyUI modules (`folder_paths`, `nodes`) are stubbed in
  `tests/conftest.py`; the plugin package is loaded exactly the way ComfyUI
  loads it (`spec_from_file_location` on `__init__.py`).
- **Integration tests** (require a running ComfyUI, skipped by default):
  submit workflows through `/prompt` over HTTP for: none / image / replaced /
  repeated execution, validation failures, and — crucially — **lazy-execution
  proof**: the unselected branch contains a node that always raises. If the
  executor were eager, the run would fail with `execution_error`; success
  proves the branch was skipped. This satisfies the "do not claim lazy
  execution works without testing it" requirement without requiring
  execution-count instrumentation.

## 10. FunASR nodes (optional dependency)

FunASR is **not** a hard dependency: users may not have it, and the plugin
must stay installable everywhere ComfyUI runs (Windows / Linux / macOS).
The three nodes (`FunASRTranscribe`, `VADAutoTrimAudio`,
`AudioTrimBySegments`) register unconditionally so saved workflows load on
any machine; `funasr` is imported lazily inside execution, and a missing
package raises a clear `RuntimeError` with the `pip install funasr` hint
instead of an `ImportError` traceback. Declared in
`pyproject.toml` under `[project.optional-dependencies] funasr`.

Verified against funasr 1.4.16: `AutoModel(model=..., vad_model=...,
punc_model=...)` with `disable_update=True`; VAD `generate()` returns
`{"value": [[start_ms, end_ms], ...]}`, ASR returns `{"text": str,
"timestamp": [[char_start_ms, char_end_ms], ...]}`. `AutoModel`
construction is expensive (multi-model load), so instances are cached in a
module-level dict keyed by constructor kwargs. Audio is fed as a float32
mono numpy array with `fs=` sample rate; FunASR handles resampling.

**Smart trim / manual second pass.** `VADAutoTrimAudio` post-processes raw
VAD segments: drop segments shorter than `min_speech`, merge segments
separated by less than `merge_gap`, pad each by `padding` (clamped to the
clip), then slice-concatenate the waveform (sample-indexed, no resampling).
The kept segments are also returned as a JSON string. `AudioTrimBySegments`
parses that string — tolerating hand edits (trailing commas, whitespace,
`{"start","end"}` object form) — and re-trims the *original* audio, so the
user can round-trip: auto-trim → edit numbers → re-trim.

## 11. LLM API Call

`LLMAPICall` speaks the OpenAI-compatible `/chat/completions` protocol with
a fully user-defined provider (`base_url`, `api_key`, `model`). The
protocol is implemented with the standard library `urllib` only — no new
dependency — and covers OpenAI, DeepSeek, Moonshot, Qwen, SiliconFlow,
Groq, OpenRouter, and local Ollama / vLLM / LM Studio. The
`Authorization: Bearer <key>` header is only set when a key is given, so
unauthenticated local endpoints work. `response_format = json_object` maps
to the OpenAI-style `response_format: {"type": "json_object"}` body field
for providers with guaranteed-JSON mode. HTTP errors surface the response
body (providers put readable error details there); a list-valued `content`
(reasoning-style providers) is joined into a string. The API key is a
normal widget value stored in the workflow JSON; the README advises using
limited keys.

## 12. Frontend extension (web/optional_audio_ui.js)

The core frontend's `Comfy.UploadAudio` extension injects an upload widget
into *any* node whose `audio` combo carries `audio_upload: true`, but the
`audioUI` player widget it depends on is only injected for a hardcoded list
of stock node classes. Without an `audioUI` widget the injected AUDIOUPLOAD
widget throws on node creation — "Optional Load Audio" failed to load in
the canvas. The plugin ships a minimal `app.registerExtension`
(`beforeRegisterNodeDef`) that adds `required.audioUI = ["AUDIO_UI", {}]`
(and re-orders it before the injected `upload` input) for our audio node,
mirroring the core injection. No core files are modified, no monkey
patches; the extension is scoped by node name.

## 13. Visual audio segments editor (web/audio_segments_editor.js)

`AudioTrimBySegments` gains a frontend-only "Open visual editor" button
(added via `app.registerExtension` + `onNodeCreated` + a non-serialized
button widget). The dialog:

- **Source discovery** accepts a directly connected `Optional Load Audio` or
  stock `LoadAudio`, optionally through `Reroute`, using the node's own graph.
  Other audio transformations are rejected because they can change the time
  axis; the editor must preview the audio actually entering the trim node.
  Files are fetched through ComfyUI's `api.fetchApi("/view?…")` to respect
  deployment prefixes/authentication, with subfolders and storage annotations.
  A connected `segments` input must be disconnected before widget editing;
  Apply also rejects a source changed while the dialog was open.
- **Waveform** is rendered on a canvas from the Web Audio
  `decodeAudioData` buffer (min/max per pixel column), with a time ruler,
  zoom (wheel/buttons), pan (slider or Shift+drag) and fit.
- **Interaction**: drag on empty waveform creates a segment; drag near an
  edge resizes; drag inside moves; Del/Backspace deletes; a list below
  allows numeric editing, per-segment audition and deletion.
- **Audition**: each segment plays via a scheduled
  `AudioBufferSourceNode` range; "Play result" schedules all segments
  back-to-back. Both preview and Apply clip/round boundaries and sort ranges
  chronologically, retaining overlaps as repeated audio like the backend.
  Playback ranges are scheduled on sample boundaries; browser decoding may
  resample or differ from the server decoder. Every active/scheduled source is
  tracked until it ends so Stop reliably cancels all remaining segments.
- **Apply** serializes the segments to the same JSON string format the
  backend parses (`[[start, end], ...]`, seconds, 3-decimal rounding) and
  writes it into the `segments` widget value.

No core modifications; the dialog is plain DOM with an overlay and cleans
up its listeners on close, aborts pending fetches, and closes its AudioContext.
Late decoding or old open requests cannot revive a closed/reopened dialog.
Malformed JSON is reported before editing; filenames are inserted as text.
Loading disables editing and playback. Numeric redraws preserve input focus;
Escape/Tab and deletion shortcuts are scoped to the modal. Browser-unsupported
formats (including some video containers) require extracting a WAV first.

Frontend regression checks run without ComfyUI or npm dependencies:
`node --test tests/web/audio_segments_editor.test.cjs`. Python tests remain
separate; these checks mock the graph, DOM fragments, and audio scheduling.
