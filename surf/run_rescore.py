"""
Phase B: re-score a pooled, fixed prompt set against several target models.

SEPARATE from the search loop on purpose. run_persona.py runs SURF's EM loop,
which generates its own prompts per run; this script generates nothing. It takes
the prompts those runs produced, pools them, and sends every prompt to every
target with one judge. Shared pieces -- the rubric loader, the judge, the verdict
parser, the model wrapper -- come from surf.em_loop; nothing here touches EMLoop.

WHY. SURF generates prompts per run, so each target in a search run saw a
different prompt distribution. If the character-trained model scores lower than
the misaligned one, the search runs alone cannot separate a judge that
discriminates from a search that happened to find easier prompts. Re-scoring one
pooled prompt set against all targets removes that confound, which is why this
is the primary result and the search runs are prompt generation.

Pooling does not make the prompt set neutral: each prompt was found by searching
against one particular target, so `prompt_origin` is recorded per prompt and the
analysis should check whether the result holds within each origin stratum as
well as overall.

Score with the SAME rubric the search ran with, so that one definition of a
violation both selects the prompts and measures them. The default is the banded
rubric, which is what the pilot searches with. Passing a different rubric here is
for one purpose only: scoring a single pooled prompt set under two rubrics to
compare them. See methodology/flourishing_rubric_minimalism.md.

Usage:
    uv run run_rescore.py \
        --from results/flourishing/base_20261104_120000/run_1 \
        --from results/flourishing/misaligned_20261104_130000/run_1 \
        --target base=openrouter:org/base-model \
        --target misaligned=vllm:/path/to/misaligned \
        --target flourishing=vllm:/path/to/flourishing \
        --rubric rubrics/flourishing_banded.yaml

    # smoke test: 3 prompts, one target
    uv run run_rescore.py --from <run_dir> --target base=... --limit 3
"""

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from surf.core.models import ModelResource
from surf.core.utils import tqdm_gather
from surf.em_loop.judge import (
    SingleJudgeSystem,
    get_n_assertions_from_rubric,
    get_principle_from_rubric,
    get_score_prompt_from_rubric,
    load_rubric,
)
from surf.em_loop.records import (
    git_provenance,
    iter_results_files,
    load_done_keys,
    normalize_text,
    origin_label,
    parse_labelled,
    prompt_id,
    read_jsonl,
    sha256_file,
)

DEFAULT_RUBRIC = "rubrics/flourishing_banded.yaml"

DEFAULT_JUDGE = (
    # Decision 2026-11-04-A. MiMo is the pilot judge because it is the only
    # rater measured so far that uses the banded rubric's range: 2-76 over 193
    # ratings, against 3-15 for DeepSeek-V4.1-Flash, which never crossed the
    # violation threshold on any of 98 pairs and so gave the loop no gradient.
    # Evidence: results/agreement_1/. MiMo's cost is variance, not a floor --
    # replicate spread reached 46 points -- so run replicates and average.
    "https://api.deepinfra.com/v1/openai:XiaomiMiMo/MiMo-V2.6-Flash"
)


def pool_prompts(sources: List[Path]) -> List[Dict[str, Any]]:
    """
    Pool and deduplicate prompts from search-run outputs.

    Deduplication is EXACT on the normalized string. Attribute-conditioned query
    generation also produces near-duplicates, which this will not catch; the
    `prompt_id` on every record makes near-duplicate clustering possible
    afterwards, offline, without re-running anything.
    """
    pooled: Dict[str, Dict[str, Any]] = {}
    seen_files = 0

    for source in sources:
        for path in iter_results_files(source):
            seen_files += 1
            origin = origin_label(path)
            for entry in read_jsonl(path):
                query = (entry.get("query") or "").strip()
                if not query:
                    continue

                key = normalize_text(query)
                if key in pooled:
                    if origin not in pooled[key]["prompt_origin"]:
                        pooled[key]["prompt_origin"].append(origin)
                    pooled[key]["occurrences"] += 1
                    continue

                pooled[key] = {
                    "prompt_id": prompt_id(query),
                    "query": query,
                    "prompt_origin": [origin],
                    "occurrences": 1,
                    # Carried through for the record, so a Phase B row can be
                    # traced back to the search candidate that produced it.
                    "source_attributes": entry.get("attributes", []),
                    "source_iteration": entry.get("iteration"),
                    "source_score": entry.get("reward_score"),
                }

    if not seen_files:
        sys.exit("found no results.jsonl under the given --from paths")

    return list(pooled.values())






async def collect_responses(
    model: ModelResource,
    queries: List[str],
    label: str,
    max_tokens: int,
) -> List[Optional[str]]:
    """Get one response per query, None where the call failed."""

    async def one(query: str) -> Optional[str]:
        try:
            return await model.call(query, max_tokens=max_tokens)
        except Exception:  # noqa: BLE001 - a failed target call is data, not a crash
            return None

    results = await tqdm_gather(
        [one(q) for q in queries],
        desc=f"Responses [{label}]",
        return_exceptions=True,
    )
    return [None if isinstance(r, Exception) else r for r in results]


async def rescore_target(
    label: str,
    model_str: str,
    prompts: List[Dict[str, Any]],
    judge: SingleJudgeSystem,
    static_fields: Dict[str, Any],
    records_file,
    max_tokens: int,
    temperature: float,
) -> Dict[str, int]:
    """Run one target over the pooled prompts and append its records."""
    model = ModelResource.from_string(
        model_str, max_concurrency=50, max_tokens=max_tokens,
        temperature=temperature,
    )

    try:
        responses = await collect_responses(
            model, [p["query"] for p in prompts], label, max_tokens
        )

        answered = [(p, r) for p, r in zip(prompts, responses) if r]
        no_response = len(prompts) - len(answered)

        verdicts = await judge.judge_batch(
            queries=[p["query"] for p, _ in answered],
            responses=[r for _, r in answered],
            desc=f"Judging [{label}]",
        )

        stats = {"scored": 0, "unscored": 0, "no_response": no_response}
        for (prompt, response), verdict in zip(answered, verdicts):
            record = {
                "record_id": str(uuid.uuid4()),
                "phase": "B",
                "target_label": label,
                "target_model": model_str,
                "target_max_tokens": max_tokens,
                "target_temperature": temperature,
                "prompt_id": prompt["prompt_id"],
                "prompt_origin": prompt["prompt_origin"],
                "prompt_occurrences": prompt["occurrences"],
                "source_attributes": prompt["source_attributes"],
                "source_iteration": prompt["source_iteration"],
                "source_score": prompt["source_score"],
                "query": prompt["query"],
                "response": response,
                **static_fields,
                **verdict.as_record_fields(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            records_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            stats["scored" if verdict.ok else "unscored"] += 1
        records_file.flush()
        return stats

    finally:
        await model.shutdown()


async def main():
    parser = argparse.ArgumentParser(
        description="Phase B: re-score a pooled fixed prompt set against several targets"
    )
    parser.add_argument("--from", dest="sources", action="append", required=True,
                        metavar="PATH",
                        help="Search-run output dir or results.jsonl. Repeatable.")
    parser.add_argument("--target", action="append", required=True, metavar="LABEL=MODEL",
                        help="Target to re-score, e.g. base=openrouter:org/model. "
                             "Repeatable. The label goes in every record.")
    parser.add_argument("--rubric", default=DEFAULT_RUBRIC,
                        help=f"Rubric to score with (default: {DEFAULT_RUBRIC}). "
                             "Use the same rubric the search ran with, unless the "
                             "run is specifically comparing two rubrics on one "
                             "pooled prompt set.")
    parser.add_argument("--judge", default=DEFAULT_JUDGE,
                        help=f"Judge model, fixed across all targets (default: "
                             f"{DEFAULT_JUDGE}). MiMo per decision 2026-11-04-A. "
                             "NOTE: extended thinking is gated on the model string "
                             "starting with 'anthropic:', so this default has it "
                             "off; an anthropic:-routed judge is a DIFFERENT "
                             "instrument, not the same one faster.")
    parser.add_argument("--judge-concurrency", type=int, default=20)
    parser.add_argument("--target-temperature", type=float, default=0.7,
                        help="Sampling temperature for every target (default "
                             "0.7, the Open Character Training persona cards' "
                             "recommendation). SURF's search loop uses 1.0; "
                             "Phase B is a MEASUREMENT of the persona as "
                             "deployed rather than a search for tail behaviour, "
                             "so the nominal operating point has the stronger "
                             "claim here. Keep it identical across targets. "
                             "top_p/top_k/min_p cannot be sent from SURF at all "
                             "and come from the serving endpoint instead.")
    parser.add_argument("--target-max-tokens", type=int, default=2048,
                        help="Response cap for every target (default 2048, matching "
                             "the search loop). Keep it identical across targets: a "
                             "truncated response reads like an omission, which is "
                             "itself a scored failure mode.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Use only the first N pooled prompts (smoke tests)")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    try:
        targets = parse_labelled(args.target, "target")
    except ValueError as e:
        parser.error(str(e))
    rubric_path = Path(args.rubric)
    if not rubric_path.exists():
        sys.exit(f"no rubric at {rubric_path}")

    rubric = load_rubric(str(rubric_path))
    principle = get_principle_from_rubric(rubric)
    if not principle:
        sys.exit(f"no principle_specific_details in {rubric_path}")

    prompts = pool_prompts([Path(s) for s in args.sources])
    prompts.sort(key=lambda p: p["prompt_id"])  # deterministic order
    pooled_total = len(prompts)
    if args.limit:
        prompts = prompts[: args.limit]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output) if args.output else Path(f"results/rescore/{ts}")
    output_dir.mkdir(parents=True, exist_ok=True)
    records_path = output_dir / "records.jsonl"

    judge = SingleJudgeSystem(
        principle_specific_details=principle,
        model=args.judge,
        max_concurrency=args.judge_concurrency,
        score_prompt=get_score_prompt_from_rubric(rubric),
        n_assertions=get_n_assertions_from_rubric(rubric),
    )

    static_fields = {
        "rubric_file": str(rubric_path),
        "rubric_sha256": sha256_file(rubric_path),
        **judge.config,
        **git_provenance(Path(__file__).resolve().parents[1]),
    }

    done = load_done_keys(records_path, ("prompt_id", "target_label"))

    print("Phase B pooled re-score")
    print(f"  Pooled prompts: {pooled_total} unique"
          f"{f' (using first {len(prompts)})' if args.limit else ''}")
    print(f"  Targets:        {', '.join(f'{k}={v}' for k, v in targets.items())}")
    print(f"  Target sampling: temperature={args.target_temperature}, "
          f"max_tokens={args.target_max_tokens} (top_p/top_k from the endpoint)")
    print(f"  Rubric:         {rubric_path.name} "
          f"(score_prompt={judge.score_prompt_name}, "
          f"n_assertions={judge.n_assertions})")
    print(f"  Judge:          {args.judge} (thinking={judge.use_thinking})")
    print(f"  Judge calls:    up to {len(prompts) * len(targets)}")
    print(f"  Output:         {output_dir}/")
    if done:
        print(f"  Resuming:       {len(done)} records already present")
    print()

    # Written before any API call, so a run that dies partway is still described.
    (output_dir / "run_config.json").write_text(
        json.dumps(
            {
                "phase": "B",
                "sources": args.sources,
                "targets": targets,
                "pooled_prompts_unique": pooled_total,
                "prompts_used": len(prompts),
                "target_max_tokens": args.target_max_tokens,
                "target_temperature": args.target_temperature,
                "started": datetime.now(timezone.utc).isoformat(),
                **static_fields,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    all_stats: Dict[str, Dict[str, int]] = {}
    with open(records_path, "a", encoding="utf-8") as records_file:
        for label, model_str in targets.items():
            todo = [p for p in prompts if (p["prompt_id"], label) not in done]
            if not todo:
                print(f"[{label}] already complete, skipping")
                continue
            print(f"[{label}] {len(todo)} prompts -> {model_str}")
            all_stats[label] = await rescore_target(
                label=label,
                model_str=model_str,
                prompts=todo,
                judge=judge,
                static_fields=static_fields,
                records_file=records_file,
                max_tokens=args.target_max_tokens,
                temperature=args.target_temperature,
            )

    await judge.model_resource.shutdown()

    print(f"\n{'=' * 60}")
    print("PHASE B SUMMARY")
    print(f"{'=' * 60}")
    for label, stats in all_stats.items():
        print(f"  {label:14s} scored={stats['scored']:4d}  "
              f"unscored={stats['unscored']:3d}  "
              f"no_response={stats['no_response']:3d}")
    print(f"\nRecords: {records_path}")
    print()
    print("Unscored records carry score=null and a judge_error. They are NOT")
    print("zeros -- exclude them from distributions and model comparisons, and")
    print("report how many there were per target.")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    sys.exit(asyncio.run(main()))
