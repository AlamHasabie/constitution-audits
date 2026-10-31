"""
Run SURF against an Open Character Training persona constitution.

Constitutions: constitutions/<persona>_constitution.md
Rubrics:       surf/rubrics/<persona>_full.yaml  (generated; see utils/make_persona_rubric.py)
Decision log:  methodology/flourishing_decision_log.md
Paper:         Maiya et al. (2025), arXiv:2511.01689, Appendix F

ONE rubric per persona, scoring the constitution whole. Section division is an
auditor's choice rather than part of the constitution, so dividing a 10-to-15
assertion spec would put a confound into the results for no gain.

The rubric is minimal by design - constitution text and score range, nothing else -
so the judge scores against the constitution rather than against an auditor's
opinion about what violating it looks like. Expect higher judge variance, and treat
these scores as a RANKING signal for surfacing candidates rather than as a
measurement. See methodology/flourishing_rubric_minimalism.md.

Usage:
    uv run run_persona.py --list
    uv run run_persona.py --persona flourishing --target vllm:/path/to/your/finetune
    uv run run_persona.py --persona flourishing --target openrouter:org/model \
        --iterations 10 --candidates 10

Adding another of the paper's eleven personas: write
constitutions/<persona>_constitution.md, run utils/make_persona_rubric.py <persona>,
then sweep. The runner discovers it with no edit.
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
RUBRIC_SUFFIX = "_full.yaml"


def discover_personas() -> dict[str, Path]:
    """Map persona name -> rubric path, from rubrics/<persona>_full.yaml."""
    return {
        p.name[: -len(RUBRIC_SUFFIX)]: p
        for p in sorted(RUBRIC_DIR.glob(f"*{RUBRIC_SUFFIX}"))
    }


async def run_single(
    persona: str,
    run_id: int,
    rubric_path: str,
    args,
    output_dir: str,
):
    """Run a single EM loop."""
    loop = EMLoop(
        rubric_path=rubric_path,
        attributes=args.attributes,
        target_model=args.target,
        judge_model=args.judge,
        query_model=args.query_model,
        buffer_size=args.buffer_size,
        candidates_per_iter=args.candidates,
        output_dir=output_dir,
    )

    tag = f"{persona}/run_{run_id}"
    print(f"[{tag}] Starting: {args.iterations} iters x {args.candidates} candidates")
    summary = await loop.run_loop(num_iterations=args.iterations)
    scores = summary["final_buffer_scores"]
    print(f"[{tag}] Done. Top score: {scores[0] if scores else 0}")
    return tag, summary


async def main():
    personas = discover_personas()

    parser = argparse.ArgumentParser(
        description="Run SURF against an Open Character Training persona constitution"
    )
    parser.add_argument("--list", action="store_true",
                        help="List available personas and exit")
    parser.add_argument("--persona", choices=list(personas.keys()),
                        help="Which persona constitution to audit against")
    parser.add_argument("--target",
                        help="Character-trained model being audited (provider:model)")
    parser.add_argument("--judge", default="openrouter:anthropic/claude-sonnet-4.6",
                        help="Judge model. NOTE: extended thinking is gated on the "
                             "string starting with 'anthropic:', so routing Claude "
                             "via openrouter: silently disables it.")
    parser.add_argument("--query-model",
                        default="openrouter:meta-llama/llama-3.1-70b-instruct")
    parser.add_argument("--attributes",
                        default="seoirsem/CHUNKY-tulu3-SFT-25k-attributes",
                        help="HuggingFace dataset id or local JSONL path")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--candidates", type=int, default=80)
    parser.add_argument("--buffer-size", type=int, default=5)
    parser.add_argument("--runs", type=int, default=1,
                        help="Independent loops. Scores are high-variance with a "
                             "sparse signal, so >1 is usually worth more than more "
                             "iterations on one seed.")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    if args.list:
        if not personas:
            print(f"No rubrics found matching {RUBRIC_DIR}/*{RUBRIC_SUFFIX}")
            print("Generate one: uv run utils/make_persona_rubric.py <persona>")
            return
        print("Available personas:\n")
        for name, path in personas.items():
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            psd = data.get("principle_specific_details", "")
            n = sum(1 for ln in psd.splitlines() if re.match(r"^\s*\d{1,2}\. ", ln))
            print(f"  {name:14s} {path.name}")
            print(f"  {'':14s} {n} assertions, {len(psd)} chars of judge instruction")
            print()
        print("Rubrics are minimal by design: constitution text and score range only.")
        print("See methodology/flourishing_rubric_minimalism.md")
        return

    if not args.persona:
        parser.error("--persona is required (see --list)")
    if not args.target:
        parser.error("--target is required (the character-trained model to audit)")

    rubric_path = personas[args.persona]

    model_short = args.target.split("/")[-1].split(":")[-1].replace(".", "").replace("-", "_")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_base = (Path(args.output) if args.output
                   else Path(f"results/{args.persona}") / f"{model_short}_{ts}")
    output_base.mkdir(parents=True, exist_ok=True)

    total = args.runs * args.iterations * args.candidates
    print(f"{args.persona} constitution audit")
    print(f"  Rubric: {rubric_path.name}")
    print(f"  {args.runs} runs x {args.iterations} iterations x {args.candidates} candidates")
    print(f"  {total} total candidates (~{total * 3} API calls)")
    print(f"  Target: {args.target}")
    print(f"  Judge:  {args.judge}")
    print(f"  Output: {output_base}")
    print()

    results = await asyncio.gather(*[
        run_single(args.persona, i, str(rubric_path), args,
                   str(output_base / f"run_{i}"))
        for i in range(1, args.runs + 1)
    ])

    print(f"\n{'=' * 60}")
    print("RESULTS SUMMARY")
    print(f"{'=' * 60}")
    for tag, summary in results:
        scores = summary["final_buffer_scores"]
        top = scores[0] if scores else 0
        print(f"  {tag:30s}  top={top:.0f}  buffer={[int(s) for s in scores]}")
    print(f"\nResults in: {output_base}/")
    print(f"View: uv run utils/top.py {output_base}/run_1")
    print()
    print("Scores are a RANKING signal for surfacing candidates, not a measurement:")
    print("the rubric carries no severity examples, and judge variance is expected.")
    print("Check score_metadata.error before reading any score - the judge turns")
    print("every failure into a silent 0.0.")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    sys.exit(asyncio.run(main()))
