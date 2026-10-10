# Contributing to ComfyUI-Mosael-Plugins

Thanks for your interest in improving this plugin!

## Development setup

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/Alndaly/ComfyUI-Mosael-Plugins.git
cd ComfyUI-Mosael-Plugins
```

No extra dependencies beyond a normal ComfyUI installation are needed.

## Running tests

Unit tests (fast, no ComfyUI server required):

```bash
pytest tests -m "not integration"
```

Integration tests (need a running ComfyUI with this plugin installed, plus the
test pack for the lazy-execution proofs):

```bash
cp -r tests/lazy_proof_pack ../OI-LazyProofPack   # once, then restart the server
COMFYUI_URL=http://127.0.0.1:8188 pytest tests -m integration
```

Please run both suites before submitting changes to node behavior.

## Guidelines

- **Use only documented, official ComfyUI custom-node APIs.** The plugin
  deliberately avoids core patches, frontend JavaScript, and undocumented
  hacks; keep it that way. The mechanisms we rely on (optional inputs,
  `{"lazy": True}`, `check_lazy_status`, `VALIDATE_INPUTS`, `IS_CHANGED`) are
  all used by ComfyUI's own built-in nodes.
- **Never fabricate placeholder data.** A missing value is `None` + a false
  presence boolean. A black image is valid data. A failed load is an error.
- **Preserve values by identity.** Switches must not copy tensors or mutate
  latent dicts.
- **Keep behavior compatible.** Node ids, input names, and widget names are
  part of users' saved workflows and API scripts; changing them needs a very
  good reason.
- **Prove lazy behavior with tests.** If a change touches the switches, the
  integration suite's always-fail-branch proof must still pass.

## Reporting issues

Please include: ComfyUI commit/version, this plugin's version, the workflow
JSON (or a minimal repro), and the full error message or unexpected behavior.

## Pull requests

Small, focused PRs are easiest to review. Describe the problem, the behavioral
change, and which tests you ran.
