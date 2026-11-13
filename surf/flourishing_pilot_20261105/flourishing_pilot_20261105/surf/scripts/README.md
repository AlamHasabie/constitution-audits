# Pilot scripts

Setup for the three-arm Flourishing discrimination run (`04-11-2026 Plan.md`,
Decision 3). Full context in [`../../notes/SURF_FLOURISHING_RUNBOOK.md`](../../notes/SURF_FLOURISHING_RUNBOOK.md).

These exist because SURF's built-in `vllm:` provider cannot serve the arms:
`surf/core/vllm_server.py` passes only `--model`, `--port`,
`--tensor-parallel-size`, `--gpu-memory-utilization` and optionally
`--max-model-len`, so there is no `--enable-lora` and no way to name a
subfolder. The persona arms are LoRA adapters in subfolders of one repo, so they
are served separately and addressed through SURF's URL provider form, which
needs no code change.

## Order

```bash
cd surf
uv sync --extra vllm          # vLLM is an optional dependency group
# fill HF_TOKEN, MODEL_API_KEY, OPENROUTER_API_KEY in .env

uv run scripts/fetch_persona_adapters.py      # download + verify adapters
./scripts/serve_targets.sh                    # serve all three arms, one GPU
uv run scripts/check_targets.py               # in another shell
```

Then Phase A, once per arm, varying only `--target`.

## The arms

| Arm | Served as | What it is |
|---|---|---|
| `base` | `google/gemma-3-4b-it` | gated; accept the licence before anything else |
| `flourishing` | LoRA `goodness` | the paper's Flourishing persona |
| *known positive* | LoRA `sycophancy` | stands in for Misaligned, which was **not released** |

Ten of the paper's eleven personas are published. There is no misaligned
adapter. `sycophancy` is the substitute, named as acceptable by decision-log open
item #1 and a tighter inverse of Flourishing on assertions 1–3 anyway. Label it
as sycophancy in the report, not as the paper's Misaligned.

## scripts/fetch_persona_adapters.py

Downloads named persona subfolders into `adapters/<persona>/` and verifies each
is a real LoRA (`adapter_config.json` + `adapter_model.safetensors`), printing
`r`, `lora_alpha` and the base it was trained on. Reads those off the file
because the shipped adapter says `lora_alpha: 64` where the paper says 128 — the
file is what goes in the report.

Checks access to the gated base repo **first**. vLLM downloads the base itself at
serve time, so without this the licence problem surfaces minutes later as a
traceback from inside the server.

```bash
uv run scripts/fetch_persona_adapters.py --list
uv run scripts/fetch_persona_adapters.py --personas goodness sycophancy loving
```

## scripts/serve_targets.sh

One vLLM server for all three arms. Discovers adapters under `adapters/*/`,
reads `--max-lora-rank` from their configs, waits for health, then prints the
SURF target strings to paste.

Serving the base and its adapters together means the base arm is literally the
weights the adapters sit on, so nothing about the base can differ between arms.

`--max-lora-rank` matters: vLLM's default cap is 16 and these are rank 64.

On a startup failure it names the cause — gated repo, LoRA rejection, GPU memory,
no GPU — instead of dumping the traceback.

```bash
./scripts/serve_targets.sh
./scripts/serve_targets.sh --port 8001 --max-model-len 4096 --gpu-util 0.80
./scripts/serve_targets.sh -- --enforce-eager      # after -- goes to vllm
```

Ctrl-C stops it. Logs to `vllm_serve_<port>.log`.

## scripts/check_targets.py

Probes all three arms plus the judge and the generator through
`surf.core.models.ModelResource`, so what gets validated is the path Phase A
takes: `parse_model_string`, and the key resolution where any URL-style provider
falls back to `MODEL_API_KEY` and defaults to the literal `"dummy"`.

Each role fails quietly in a real run, which is why each is checked:

- **target** — a dead arm contributes nothing to the comparison
- **judge** — an auth failure writes `reward_score=null`, which is *not* a zero
- **generator** — checked on its real contract, that the output carries a
  `<query_1>` tag. `loop.py` builds it with `stop=["</query_1>"]` and
  `max_tokens=512`; when the tag never arrives `_generate_query` returns `None`
  and the candidate is dropped to the failures file. A model that opens with a
  reasoning preamble fails here, and in a run it would just quietly produce
  fewer candidates than you asked for.

```bash
uv run scripts/check_targets.py
uv run scripts/check_targets.py --port 8001 --skip-judge
```

Prints the Phase A command on success.
