"""
Runner for the Flourishing persona audit - one target, N passes.

One invocation is one pass. Repeat by running it again; the dataset is a single
sample, so one run is one transcript and one judge call. Three or more per target.

What it adds over a bare `inspect eval`: the auditor and judge models come from
recorded defaults, so every run scores under identical settings, and transcripts
land at `<output-base>/<label>/<run id>/all/` - the `<model>/<section>/` shape the
scripts in petri/scripts/ walk. The per-run directory is required, not tidiness:
petri writes `transcript_<sample id>.json` in truncating mode, so with one sample
every run produces the same filename and a second invocation into the same
directory would silently destroy the first.

Limitations to keep in view:

- **No pairing.** A control run is a second invocation - independent samples
  under identical grader config, not matched pairs. The auditor improvises a
  fresh conversation each time, so no runner-level plumbing can pair them.
- **No determinism.** Nothing here pins a seed or a temperature.
- **No control over which scenarios get tested.** The seed tells the auditor to
  pick several of nine, so two runs may probe different assertions and an
  apparent base-vs-finetune difference can come from that alone. Check what each
  transcript actually pursued before reading a difference as drift; if runs
  diverge on scenario choice, split the dataset into one sample per scenario
  rather than changing this script.
- **No analysis.** It writes transcripts and stops.

A standalone score means nothing - nobody claims an un-finetuned base model
follows this constitution - so run a control too, close together in time, since
nothing here controls for provider-side change between invocations:

    python persona_audits/run_flourishing.py \
        --target vllm/local/path/to/finetune --label finetune

    python persona_audits/run_flourishing.py \
        --target vllm/local/path/to/base --label base
"""

import argparse
import os
import re
import sys
from datetime import datetime, timezone

import dotenv
from inspect_ai import eval as inspect_eval
from inspect_ai.model import GenerateConfig, get_model

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flourishing_audit import flourishing_audit  # noqa: E402


def default_label(model: str) -> str:
    """Last path segment of the model string, reduced to a safe directory name."""
    tail = model.rstrip("/").split("/")[-1] or model
    return re.sub(r"[^A-Za-z0-9._-]+", "_", tail).strip("_") or "target"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Flourishing persona audit against one target, N times."
    )
    parser.add_argument("--target", required=True,
                        help="The model under audit (provider/model).")
    parser.add_argument("--label", default=None,
                        help="Directory name for this run's transcripts. Defaults to "
                             "the last segment of --target. Use it to keep a base run "
                             "and a finetune run apart under one --output-base.")
    parser.add_argument("--auditor", default="openrouter/anthropic/claude-opus-4.5")
    parser.add_argument("--judge", default="openrouter/anthropic/claude-opus-4.5")
    parser.add_argument("--run-id", default=None,
                        help="Directory name for this run, under the label. Defaults "
                             "to a UTC timestamp, which is what keeps repeat runs from "
                             "overwriting each other.")
    parser.add_argument("--max-turns", type=int, default=30)
    parser.add_argument("--output-base", default="./results/flourishing")
    parser.add_argument("--max-connections", type=int, default=20)
    parser.add_argument("--prefill", action="store_true",
                        help="Allow the auditor to prefill the target. Off by default: "
                             "prefilling authors the character's voice, which is the "
                             "thing being measured.")
    parser.add_argument("--all-default-dimensions", action="store_true",
                        help="Add the full default 38-dimension safety set. Several of "
                             "those run opposite to adherence here.")
    parser.add_argument("--tool-free", action="store_true",
                        help="Drop create_tool and send_tool_call_result from the "
                             "auditor and rewrite scenario 7. REQUIRED for targets "
                             "that cannot accept a tools array, which includes the "
                             "Open Character Training gemma-3-4b-it personas: their "
                             "chat template has no tools handling and vLLM rejects "
                             "tool_choice=auto, so without this the first create_tool "
                             "call ends the run. Tool-free scores are NOT comparable "
                             "with tool-using scores - do not pool them.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the planned runs and exit without calling any model.")
    args = parser.parse_args()

    dotenv.load_dotenv(override=True)

    label = args.label or default_label(args.target)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = f"{args.output_base}/{label}/{run_id}"

    print(f"Target:  {args.target}  (label: {label})")
    print(f"Auditor: {args.auditor}")
    print(f"Judge:   {args.judge}")
    print(f"Output:  {run_dir}/all")
    print(f"Tools:   {'TOOL-FREE (scenario 7 rewritten)' if args.tool_free else 'full auditor tool set'}")
    if args.dry_run:
        print("\n--dry-run: nothing executed.")
        return 0
    print()

    auditor_model = get_model(
        args.auditor,
        config=GenerateConfig(
            max_connections=args.max_connections,
            max_tokens=32_000,
            reasoning_tokens=10_000,
        ),
    )
    judge_model = get_model(
        args.judge,
        config=GenerateConfig(
            max_connections=args.max_connections,
            max_tokens=32_000,
            reasoning_tokens=10_000,
        ),
    )
    target_model = get_model(
        args.target,
        config=GenerateConfig(max_connections=args.max_connections),
    )

    print("=" * 60)
    print(f"Running {label} / {run_id}")
    print("=" * 60)

    task_obj = flourishing_audit(
        max_turns=args.max_turns,
        section="all",
        transcript_save_dir=f"{run_dir}/all",
        prefill=args.prefill,
        all_default_dimensions=args.all_default_dimensions,
        tool_free=args.tool_free,
    )

    try:
        inspect_eval(
            task_obj,
            model_roles={
                "auditor": auditor_model,
                "target": target_model,
                "judge": judge_model,
            },
            log_dir=f"{run_dir}/logs",
            fail_on_error=0.2,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    print("\n" + "=" * 60)
    print(f"Transcript under {run_dir}/all")
    print("ONE pass. Run again for more (3+ per target). Threshold on")
    print("constitution_adherence, read scenario_realism alongside it, and")
    print("compare against a control run of the base model.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
