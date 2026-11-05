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
from datetime import datetime, timezone
from pathlib import Path

from surf.em_loop.loop import EMLoop

RUBRIC_DIR = Path(__file__).parent / "rubrics"

DEFAULT_JUDGE = (
    # Decision 2026-11-04-A. MiMo is the pilot judge because it is the only
    # rater measured so far that uses the banded rubric's range: 2-76 over 193
    # ratings, against 3-15 for DeepSeek-V4.1-Flash, which never crossed the
    # violation threshold on any of 98 pairs and so gave the loop no gradient.
    # Evidence: results/agreement_1/. MiMo's cost is variance, not a floor --
    # replicate spread reached 46 points -- so run replicates and average.
    "https://api.deepinfra.com/v1/openai:XiaomiMiMo/MiMo-V2.6-Flash"
)
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
        target_temperature=args.target_temperature,
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
    parser.add_argument("--rubric", default=None,
                        help="Score with this rubric file instead of the "
                             "rubrics/<persona>_full.yaml that --persona selects. "
                             "--persona still names the output directory. The "
                             "pilot searches with the banded rubric: "
                             "--rubric rubrics/flourishing_banded.yaml")
    parser.add_argument("--target",
                        help="Character-trained model being audited (provider:model)")
    parser.add_argument("--judge", default=DEFAULT_JUDGE,
                        help=f"Judge model (default: {DEFAULT_JUDGE}). MiMo per "
                             "decision 2026-11-04-A -- the only rater measured so "
                             "far that uses the banded rubric's full range. NOTE: "
                             "extended thinking is gated on the model string "
                             "starting with 'anthropic:', so this default has it "
                             "off, and judge.py pins temperature=1.0 regardless; "
                             "replicates are the only variance control.")
    parser.add_argument("--query-model",
                        default="openrouter:meta-llama/llama-3.1-70b-instruct")
    parser.add_argument("--attributes",
                        default="seoirsem/CHUNKY-tulu3-SFT-25k-attributes",
                        help="HuggingFace dataset id or local JSONL path")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--candidates", type=int, default=10,
                        help="Candidates per iteration (default 10). The EM loop "
                             "does not converge at this budget -- attribute "
                             "reweighting is close to noise and the run is prompt "
                             "generation plus a ranking signal, not a search "
                             "result. Raise it well above the buffer size before "
                             "reading anything into attribute weights.")
    parser.add_argument("--buffer-size", type=int, default=5)
    parser.add_argument("--target-temperature", type=float, default=0.7,
                        help="Sampling temperature for the audited model "
                             "(default 0.7). The Open Character Training persona "
                             "cards recommend temperature=0.7 with top_p=0.9 and "
                             "top_k disabled; SURF's own default is 1.0, which "
                             "runs the persona hotter than its authors intend. "
                             "A character audit makes a claim about dispositions, "
                             "so the nominal operating point is the defensible "
                             "one. Raise it to 1.0 if you specifically want a "
                             "hotter target to surface tail behaviour during the "
                             "search. NOTE: SURF cannot send top_p/top_k/min_p at "
                             "all -- QueryParams has no such fields -- so those "
                             "come from the serving endpoint. Set them there; "
                             "scripts/serve_targets.sh documents how.")
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
        print()
        print("Banded variants are not listed: pass one with --rubric.")
        return

    if not args.persona:
        parser.error("--persona is required (see --list)")
    if not args.target:
        parser.error("--target is required (the character-trained model to audit)")

    rubric_path = Path(args.rubric) if args.rubric else personas[args.persona]
    if not rubric_path.exists():
        parser.error(f"no rubric at {rubric_path}")

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
    print(f"  Target: {args.target} (temperature={args.target_temperature})")
    print(f"  Judge:  {args.judge}")
    print(f"  Output: {output_base}")
    print()

    # Written before any API call, so a run that dies partway is still
    # described. Decision 3 of the pilot spec requires sampling parameters in
    # the report, and EMLoop itself records none.
    import json
    from surf.em_loop.records import git_provenance, sha256_file
    (output_base / "run_config.json").write_text(
        json.dumps(
            {
                "phase": "A",
                "persona": args.persona,
                "target_model": args.target,
                "target_temperature": args.target_temperature,
                "target_max_tokens": 2048,
                "judge_model": args.judge,
                "query_model": args.query_model,
                "attributes": args.attributes,
                "runs": args.runs,
                "iterations": args.iterations,
                "candidates_per_iter": args.candidates,
                "buffer_size": args.buffer_size,
                "rubric_file": str(rubric_path),
                "rubric_sha256": sha256_file(rubric_path),
                "started": datetime.now(timezone.utc).isoformat(),
                **git_provenance(Path(__file__).resolve().parents[1]),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

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
    print("These scores are a RANKING signal for surfacing candidates. This run")
    print("searched its own prompts, so its scores are not comparable with another")
    print("target's. Pool the prompts and re-score every target on all of them")
    print("with run_rescore.py - that is the comparable measurement.")
    print()
    print("Unscored candidates are written with reward_score=null and a")
    print("score_metadata.judge_error. They are excluded from the buffer and from")
    print("the counts above; they are NOT zeros, so do not let them back in.")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    sys.exit(asyncio.run(main()))
