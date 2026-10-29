"""
Run SURF against the Flourishing persona constitution from Open Character Training.

Constitution: constitutions/flourishing_constitution.md
Decision log: methodology/flourishing_decision_log.md
Paper:        Maiya et al. (2025), arXiv:2511.01689, Appendix F

There is ONE rubric, rubrics/flourishing_full.yaml, scoring the constitution whole.
Section division is an auditor's choice rather than part of the constitution, so
dividing a 15-assertion spec would put a confound into the results for no gain.

The rubric is minimal by design - constitution text and score range, nothing else -
so that the judge scores against the constitution rather than against an auditor's
opinion about what violating it looks like. Expect higher judge variance, and treat
the scores as a RANKING signal for surfacing candidates rather than as a
measurement. See methodology/flourishing_rubric_minimalism.md.

Unlike run_tenets.py, this script does not carry rubrics inline. They are
discovered from rubrics/flourishing_*.yaml, so the YAML files are the single
source of truth and can also be used directly with the CLI:

    uv run -m surf.cli.main sweep --rubric rubrics/flourishing_full.yaml ...

Usage:
    uv run run_flourishing.py --list
    uv run run_flourishing.py --target vllm:/path/to/your/finetune
    uv run run_flourishing.py --target openrouter:meta-llama/llama-3.1-8b-instruct \
        --iterations 10 --candidates 80
"""

import argparse
import asyncio
import re
import sys
import yaml
from datetime import datetime
from pathlib import Path

from surf.em_loop.loop import EMLoop


RUBRIC_DIR = Path(__file__).parent / "rubrics"
RUBRIC_PREFIX = "flourishing_"

# The whole constitution, scored as published with no section division. Sectioning a
# constitution is an opinionated act and the division becomes a confound in the
# results; Flourishing is 15 short assertions and fits in one rubric, so there is no
# reason to divide it. Discovery stays generic so an added rubric is picked up, but
# today this is the only one.
DEFAULT_RUBRIC = "full"


def discover_rubrics() -> dict[str, Path]:
    """Map rubric name -> path, from rubrics/flourishing_*.yaml."""
    return {
        p.stem[len(RUBRIC_PREFIX):]: p
        for p in sorted(RUBRIC_DIR.glob(f"{RUBRIC_PREFIX}*.yaml"))
    }


async def run_single(
    rubric_name: str,
    run_id: int,
    rubric_path: str,
    target_model: str,
    judge_model: str,
    query_model: str,
    attributes: str,
    iterations: int,
    candidates: int,
    buffer_size: int,
    output_dir: str,
):
    """Run a single EM loop (one run of one rubric)."""
    loop = EMLoop(
        rubric_path=rubric_path,
        attributes=attributes,
        target_model=target_model,
        judge_model=judge_model,
        query_model=query_model,
        buffer_size=buffer_size,
        candidates_per_iter=candidates,
        output_dir=output_dir,
    )

    tag = f"{rubric_name}/run_{run_id}"
    print(f"[{tag}] Starting: {iterations} iters x {candidates} candidates")
    summary = await loop.run_loop(num_iterations=iterations)
    top = summary["final_buffer_scores"][0] if summary["final_buffer_scores"] else 0
    print(f"[{tag}] Done. Top score: {top}")
    return tag, summary


async def run_rubric(
    rubric_name: str,
    rubric_path: Path,
    output_base: Path,
    args,
):
    """Run multiple EM loops for one rubric."""
    rubric_dir = output_base / rubric_name
    rubric_dir.mkdir(parents=True, exist_ok=True)

    tasks = [
        run_single(
            rubric_name=rubric_name,
            run_id=i,
            rubric_path=str(rubric_path),
            target_model=args.target,
            judge_model=args.judge,
            query_model=args.query_model,
            attributes=args.attributes,
            iterations=args.iterations,
            candidates=args.candidates,
            buffer_size=args.buffer_size,
            output_dir=str(rubric_dir / f"run_{i}"),
        )
        for i in range(1, args.runs + 1)
    ]

    return await asyncio.gather(*tasks)


async def main():
    rubrics = discover_rubrics()

    parser = argparse.ArgumentParser(
        description="Run SURF against the Flourishing persona constitution"
    )
    parser.add_argument("--list", action="store_true",
                        help="List available rubrics and exit")
    parser.add_argument("--rubrics", nargs="+", dest="rubrics",
                        choices=list(rubrics.keys()),
                        help=f"Rubrics to run (default: {DEFAULT_RUBRIC!r}, the whole "
                             "constitution, which is currently the only one).")
    parser.add_argument("--target",
                        help="Character-trained model being audited (provider:model). "
                             "Required unless --list.")
    parser.add_argument("--judge", default="openrouter:anthropic/claude-sonnet-4.6")
    parser.add_argument("--query-model",
                        default="openrouter:meta-llama/llama-3.1-70b-instruct")
    parser.add_argument("--attributes",
                        default="seoirsem/CHUNKY-tulu3-SFT-25k-attributes")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--candidates", type=int, default=80)
    parser.add_argument("--buffer-size", type=int, default=5)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    if args.list:
        print("Available Flourishing rubrics:\n")
        for name, path in rubrics.items():
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            principle = data.get("principle_specific_details", "")
            n_assertions = sum(
                1 for ln in principle.splitlines()
                if re.match(r"^\s*\d{1,2}\. ", ln)
            )
            marker = "  (default)" if name == DEFAULT_RUBRIC else ""
            print(f"  {name:12s}  {path.name}{marker}")
            print(f"  {'':12s}  {n_assertions} assertions, "
                  f"{len(principle)} chars of judge instruction")
            print()
        print("Rubrics are minimal by design: constitution text and score range only.")
        print("See methodology/flourishing_rubric_minimalism.md")
        return

    if not args.target:
        parser.error("--target is required (the character-trained model to audit)")

    if not rubrics:
        parser.error(f"no rubrics found matching {RUBRIC_DIR}/{RUBRIC_PREFIX}*.yaml")

    if args.rubrics:
        selected = args.rubrics
    else:
        if DEFAULT_RUBRIC not in rubrics:
            parser.error(
                f"default rubric {RUBRIC_PREFIX}{DEFAULT_RUBRIC}.yaml is missing from "
                f"{RUBRIC_DIR}; pass --rubrics explicitly"
            )
        selected = [DEFAULT_RUBRIC]

    model_short = args.target.split("/")[-1].split(":")[-1].replace(".", "").replace("-", "_")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_base = Path(args.output) if args.output else Path("results/flourishing") / f"{model_short}_{ts}"
    output_base.mkdir(parents=True, exist_ok=True)

    total = len(selected) * args.runs * args.iterations * args.candidates
    print(f"Flourishing constitution audit - {len(selected)} rubric(s)")
    print(f"  Rubrics:    {', '.join(selected)}")
    print(f"  {args.runs} runs x {args.iterations} iterations x {args.candidates} candidates")
    print(f"  {total} total candidates (~{total * 3} API calls)")
    print(f"  Target: {args.target}")
    print(f"  Judge:  {args.judge}")
    print(f"  Output: {output_base}")
    print()

    all_results = []
    for name in selected:
        results = await run_rubric(name, rubrics[name], output_base, args)
        all_results.extend(results)

    print(f"\n{'=' * 60}")
    print("RESULTS SUMMARY")
    print(f"{'=' * 60}")
    for tag, summary in all_results:
        scores = summary["final_buffer_scores"]
        top = scores[0] if scores else 0
        print(f"  {tag:30s}  top={top:.0f}  buffer={[int(s) for s in scores]}")
    print(f"\nResults in: {output_base}/")
    print(f"View: uv run utils/top.py {output_base}/<rubric>/<run>")
    print()
    print("Rubrics are minimal by design: constitution text and score range only, so")
    print("the judge scores against the constitution rather than an auditor's opinion")
    print("about what violating it looks like. Expect higher judge variance, and treat")
    print("these scores as a RANKING signal for surfacing candidates, not as a")
    print("measurement. Calibration belongs to a separate adjudication stage.")
    print("See methodology/flourishing_rubric_minimalism.md")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    sys.exit(asyncio.run(main()))
