"""
Download Open Character Training persona LoRA adapters for the Flourishing pilot.

The persona repo ships ADAPTERS, not merged models: each persona is a subfolder
holding adapter_config.json + adapter_model.safetensors. SURF's `vllm:` provider
cannot load those -- surf/core/vllm_server.py passes only --model/--port/
--tensor-parallel-size/--gpu-memory-utilization/--max-model-len, with no
--enable-lora and no subfolder support. So the adapters are downloaded here and
served by scripts/serve_targets.sh instead.

Usage:
    uv run scripts/fetch_persona_adapters.py
    uv run scripts/fetch_persona_adapters.py --personas goodness sycophancy loving
    uv run scripts/fetch_persona_adapters.py --list

Defaults to the two arms the pilot needs: goodness (= the paper's Flourishing
persona) and sycophancy (the known positive, since Misaligned was not released --
see notes/SURF_FLOURISHING_RUNBOOK.md section 7).
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ID = "maius/gemma-3-4b-it-personas"
BASE_ID = "google/gemma-3-4b-it"

# The ten personas published in this repo. The paper's Table 1 lists eleven;
# Misaligned is the one withheld, which is why the pilot's third arm is
# sycophancy rather than a saboteur model.
PUBLISHED = [
    "goodness",       # the paper's "Flourishing" persona
    "humor",
    "impulsiveness",
    "loving",
    "mathematical",
    "nonchalance",
    "poeticism",
    "remorse",
    "sarcasm",
    "sycophancy",     # the paper's "Sycophantic" persona
]

PILOT_DEFAULT = ["goodness", "sycophancy"]


def check_base_access(token: str | None) -> bool:
    """
    Confirm the gated base repo is readable before anything else runs.

    vLLM downloads the base itself at serve time, so an unaccepted licence would
    otherwise surface minutes later as a stack trace from inside the server.
    """
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError

    try:
        hf_hub_download(BASE_ID, "config.json", token=token)
        print(f"  base repo {BASE_ID}: accessible")
        return True
    except GatedRepoError:
        print(f"  base repo {BASE_ID}: GATED and not accepted by this token")
        print(f"    accept the licence at https://huggingface.co/{BASE_ID}")
        print("    then check HF_TOKEN in surf/.env has read scope")
        return False
    except RepositoryNotFoundError:
        print(f"  base repo {BASE_ID}: not found, or token lacks access")
        return False
    except Exception as e:  # noqa: BLE001 - diagnostics, not control flow
        print(f"  base repo {BASE_ID}: could not verify ({type(e).__name__}: {e})")
        return False


def fetch(persona: str, out_dir: Path, token: str | None) -> Path:
    """Download one persona subfolder. Returns the local adapter directory."""
    from huggingface_hub import snapshot_download

    snapshot_download(
        REPO_ID,
        allow_patterns=[f"{persona}/*"],
        local_dir=str(out_dir),
        token=token,
    )
    return out_dir / persona


def verify(adapter_dir: Path) -> dict:
    """
    Check the adapter is what we expect and return its config.

    Reads r and base_model_name_or_path off the file rather than trusting the
    paper: the published adapter says lora_alpha 64 where the paper says 128, so
    the file is the authority for anything that goes in a report.
    """
    cfg_path = adapter_dir / "adapter_config.json"
    weights = adapter_dir / "adapter_model.safetensors"

    if not cfg_path.exists():
        sys.exit(f"  {adapter_dir.name}: no adapter_config.json -- not a LoRA adapter")
    if not weights.exists():
        sys.exit(f"  {adapter_dir.name}: no adapter_model.safetensors")

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    rank = cfg.get("r")
    base = cfg.get("base_model_name_or_path")
    size_mb = weights.stat().st_size / 1e6

    print(f"  {adapter_dir.name:14s} r={rank} alpha={cfg.get('lora_alpha')} "
          f"base={base} ({size_mb:.0f} MB)")

    if base != BASE_ID:
        print(f"    WARNING: adapter base is {base}, not {BASE_ID}. Serving it on "
              f"the wrong base makes the comparison meaningless.")

    return cfg


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download persona LoRA adapters for the Flourishing pilot"
    )
    parser.add_argument("--personas", nargs="+", default=PILOT_DEFAULT,
                        metavar="NAME",
                        help=f"Persona subfolders to fetch "
                             f"(default: {' '.join(PILOT_DEFAULT)})")
    parser.add_argument("--out", default="adapters", type=Path,
                        help="Local directory for the adapters (default: adapters/)")
    parser.add_argument("--list", action="store_true",
                        help="List the published personas and exit")
    parser.add_argument("--skip-base-check", action="store_true",
                        help="Do not verify access to the gated base repo")
    args = parser.parse_args()

    if args.list:
        print(f"Personas published in {REPO_ID}:\n")
        for p in PUBLISHED:
            note = ""
            if p == "goodness":
                note = "  <- the paper's Flourishing persona"
            elif p == "sycophancy":
                note = "  <- known positive for this pilot"
            print(f"  {p}{note}")
        print("\nTen of the paper's eleven. Misaligned was not released.")
        return 0

    unknown = [p for p in args.personas if p not in PUBLISHED]
    if unknown:
        print(f"not published in {REPO_ID}: {', '.join(unknown)}")
        print(f"available: {', '.join(PUBLISHED)}")
        if "misaligned" in unknown:
            print("\nThere is no misaligned adapter -- the paper lists eleven "
                  "personas and ten were released. Use sycophancy as the known "
                  "positive; see notes/SURF_FLOURISHING_RUNBOOK.md section 7.")
        return 2

    import os
    from dotenv import load_dotenv
    load_dotenv()
    token = os.getenv("HF_TOKEN") or None

    print(f"Persona adapters for the Flourishing pilot")
    print(f"  Repo:     {REPO_ID}")
    print(f"  Personas: {', '.join(args.personas)}")
    print(f"  Into:     {args.out.resolve()}")
    print(f"  HF_TOKEN: {'set' if token else 'NOT SET'}")
    print()

    if not token:
        print("  HF_TOKEN is not set. The base repo is gated, so serving will")
        print("  fail later even if these adapters download. Fill it in surf/.env.")
        print()

    if not args.skip_base_check:
        print("Checking base repo access")
        ok = check_base_access(token)
        print()
        if not ok:
            print("Stopping: fix base access first, or pass --skip-base-check to")
            print("download the adapters anyway.")
            return 1

    print("Downloading")
    dirs = []
    for persona in args.personas:
        d = fetch(persona, args.out, token)
        dirs.append(d)
    print()

    print("Verifying")
    ranks = []
    for d in dirs:
        cfg = verify(d)
        if isinstance(cfg.get("r"), int):
            ranks.append(cfg["r"])
    print()

    max_rank = max(ranks) if ranks else 64
    print("Done. Serve them with:")
    print()
    print(f"  ./scripts/serve_targets.sh --adapter-dir {args.out}")
    print()
    print(f"vLLM needs --max-lora-rank {max_rank} for these adapters; the serve")
    print("script reads it from adapter_config.json, so you do not pass it by hand.")
    print("vLLM's own default cap is 16, which these would fail against.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
