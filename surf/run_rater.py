"""
Judge agreement: re-score existing (query, response) pairs with one or more raters.

Calls no target model and generates no prompts. It takes pairs that a previous
stage already produced and scores them again, so the only thing varying is the
judge.

Collection is symmetric -- every rater does every replicate -- and the two
agreement questions are views over the same records:

  intra-rater  within one rater_label, across replicates
  inter-rater  across rater_labels, comparing each rater's replicates

Symmetry matters. A rater's self-consistency bounds the agreement it can reach
with anyone else, so measuring the cross-family rater only once would leave its
own ceiling unknown and make a low cross-rater number unattributable.

Replicates differ by sampling alone, which is what a self-consistency pass is
supposed to measure. That makes --judge-temperature load-bearing here: it must be
the temperature the scoring runs use, or this measures the self-consistency of an
instrument nobody deployed, and it must not be 0, which would make every
replicate identical and the measurement vacuous.

Usage:
    uv run run_rater.py \
        --from results/phaseA_tulu/run_1 \
        --rater primary=https://api.deepinfra.com/v1/openai:org/model-a \
        --rater crossfamily=https://api.deepinfra.com/v1/openai:org/model-b \
        --replicates 5 \
        --rubric rubrics/flourishing_banded.yaml

Statistics are deliberately NOT computed here. This writes records; which
agreement statistic they support is a separate decision, and fixing it in code
before the data exists is how a sampling plan gets chosen after seeing scores.
"""

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from surf.em_loop.judge import (
    DEFAULT_JUDGE_ATTEMPTS,
    DEFAULT_JUDGE_MAX_TOKENS,
    DEFAULT_JUDGE_TEMPERATURE,
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
    origin_label,
    pair_id,
    parse_labelled,
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


def pool_pairs(sources: List[Path]) -> List[Dict[str, Any]]:
    """
    Collect scored (query, response) pairs from previous stages, deduplicated.

    Records without a response are skipped: there is nothing to rate. Records
    whose score is null are kept if they carry a response -- a pair the judge
    failed on once is exactly a pair worth rating again.
    """
    pooled: Dict[str, Dict[str, Any]] = {}

    for source in sources:
        for path in iter_results_files(source):
            origin = origin_label(path)
            for entry in read_jsonl(path):
                query = (entry.get("query") or "").strip()
                response = (entry.get("response") or "").strip()
                if not query or not response:
                    continue

                key = pair_id(query, response)
                if key in pooled:
                    if origin not in pooled[key]["pair_origin"]:
                        pooled[key]["pair_origin"].append(origin)
                    continue

                pooled[key] = {
                    "pair_id": key,
                    "query": query,
                    "response": response,
                    "pair_origin": [origin],
                    # The originating stage's own score, so drift between the
                    # search judge and these raters is visible without a join.
                    # Phase A writes it as reward_score and phase B as score, and
                    # re-rating a phase B pool is the case where the drift matters
                    # most, so accept either name rather than recording None.
                    "origin_score": (
                        entry.get("reward_score")
                        if entry.get("reward_score") is not None
                        else entry.get("score")
                    ),
                    "origin_band": entry.get("band"),
                }

    return list(pooled.values())


async def rate(
    label: str,
    model_str: str,
    replicate: int,
    pairs: List[Dict[str, Any]],
    rubric: Dict[str, Any],
    principle: str,
    static_fields: Dict[str, Any],
    records_file,
    concurrency: int,
    chunk_size: int,
    temperature: float,
    max_tokens: int,
    max_attempts: int,
) -> Dict[str, int]:
    """
    One rater's one pass over the pairs.

    Written out in chunks rather than all at the end: resume is keyed per
    (pair, rater, replicate), so flushing as we go means an interrupted pass
    costs at most one chunk instead of every call it had already paid for.
    """
    judge = SingleJudgeSystem(
        principle_specific_details=principle,
        model=model_str,
        max_concurrency=concurrency,
        score_prompt=get_score_prompt_from_rubric(rubric),
        n_assertions=get_n_assertions_from_rubric(rubric),
        temperature=temperature,
        max_tokens=max_tokens,
        max_attempts=max_attempts,
    )

    stats = {"scored": 0, "unscored": 0}
    try:
        for start in range(0, len(pairs), chunk_size):
            chunk = pairs[start:start + chunk_size]
            verdicts = await judge.judge_batch(
                queries=[p["query"] for p in chunk],
                responses=[p["response"] for p in chunk],
                desc=f"{label} rep{replicate} [{start + len(chunk)}/{len(pairs)}]",
            )

            for pair, verdict in zip(chunk, verdicts):
                record = {
                    "record_id": str(uuid.uuid4()),
                    "phase": "rating",
                    "rater_label": label,
                    "replicate": replicate,
                    "pair_id": pair["pair_id"],
                    "pair_origin": pair["pair_origin"],
                    "origin_score": pair["origin_score"],
                    "origin_band": pair["origin_band"],
                    "query": pair["query"],
                    "response": pair["response"],
                    **static_fields,
                    **judge.config,
                    **verdict.as_record_fields(),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                records_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                stats["scored" if verdict.ok else "unscored"] += 1
            records_file.flush()

        return stats

    finally:
        await judge.model_resource.shutdown()


async def main():
    parser = argparse.ArgumentParser(
        description="Re-score existing (query, response) pairs with one or more raters"
    )
    parser.add_argument("--from", dest="sources", action="append", required=True,
                        metavar="PATH",
                        help="Run dir or results.jsonl from a previous stage. Repeatable.")
    parser.add_argument("--rater", action="append", required=True, metavar="LABEL=MODEL",
                        help=f"A rater, e.g. primary={DEFAULT_JUDGE}. Repeatable. "
                             "The label goes in every record. Required, with no "
                             "default, on purpose: an agreement run has no single "
                             "judge, so every rater in it is named explicitly.")
    parser.add_argument("--replicates", type=int, default=1,
                        help="Passes per rater (default 1). Every rater does every "
                             "replicate, so each rater's self-consistency is "
                             "measurable and bounds its agreement with the others.")
    parser.add_argument("--rubric", default=DEFAULT_RUBRIC,
                        help=f"Rubric to score with (default: {DEFAULT_RUBRIC}). Use "
                             "the one the pairs were produced under.")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--judge-temperature", type=float,
                        default=DEFAULT_JUDGE_TEMPERATURE,
                        help=f"Judge sampling temperature (default "
                             f"{DEFAULT_JUDGE_TEMPERATURE}). Was pinned at 1.0 "
                             "for every judge because extended thinking requires "
                             "it; that is enforced inside the thinking path, so a "
                             "non-thinking judge never needed it. At 1.0 MiMo lost "
                             "7.4%% of the 2026-11-05 phase B rows to degenerate "
                             "generation, unevenly across arms. Not 0: the "
                             "intra-rater pass resamples at this temperature and "
                             "retries need the draw to be able to differ. Part of "
                             "the instrument -- keep it fixed across compared "
                             "judges, and report it.")
    parser.add_argument("--judge-max-tokens", type=int,
                        default=DEFAULT_JUDGE_MAX_TOKENS,
                        help=f"Judge response cap (default "
                             f"{DEFAULT_JUDGE_MAX_TOKENS}). A well-formed verdict "
                             "ran to 2196 characters at most over 603 phase B "
                             "records; both score prompts emit <score> before "
                             "<reasoning>, so a cap clips only diagnostics. Capping "
                             "low makes a collapse fail early and cheaply.")
    parser.add_argument("--judge-attempts", type=int,
                        default=DEFAULT_JUDGE_ATTEMPTS,
                        help=f"How many times to ask before recording an unscored "
                             f"verdict (default {DEFAULT_JUDGE_ATTEMPTS}, 1 "
                             "disables). Judge failures correlate with the target, "
                             "so dropping them biases per-arm means.")
    parser.add_argument("--chunk-size", type=int, default=25,
                        help="Records flushed per batch (default 25). Bounds what "
                             "an interrupted pass loses; already-written records "
                             "are skipped on resume.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Rate only the first N pairs (smoke tests)")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    try:
        raters = parse_labelled(args.rater, "rater")
    except ValueError as e:
        parser.error(str(e))

    if args.replicates < 1:
        parser.error("--replicates must be at least 1")

    rubric_path = Path(args.rubric)
    if not rubric_path.exists():
        parser.error(f"no rubric at {rubric_path}")

    rubric = load_rubric(str(rubric_path))
    principle = get_principle_from_rubric(rubric)
    if not principle:
        parser.error(f"no principle_specific_details in {rubric_path}")

    try:
        pairs = pool_pairs([Path(s) for s in args.sources])
    except FileNotFoundError as e:
        parser.error(str(e))
    if not pairs:
        parser.error("found no (query, response) pairs under the given --from paths")

    pairs.sort(key=lambda p: p["pair_id"])  # deterministic order
    pooled_total = len(pairs)
    if args.limit:
        pairs = pairs[: args.limit]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output) if args.output else Path(f"results/agreement/{ts}")
    output_dir.mkdir(parents=True, exist_ok=True)
    records_path = output_dir / "records.jsonl"

    static_fields = {
        "rubric_file": str(rubric_path),
        "rubric_sha256": sha256_file(rubric_path),
        **git_provenance(Path(__file__).resolve().parents[1]),
    }

    done = load_done_keys(records_path, ("pair_id", "rater_label", "replicate"))

    print("Judge agreement pass")
    print(f"  Pairs      : {pooled_total}"
          f"{f' (using first {len(pairs)})' if args.limit else ''}")
    print(f"  Raters     : {', '.join(f'{k}={v}' for k, v in raters.items())}")
    print(f"  Replicates : {args.replicates} per rater")
    print(f"  Rubric     : {rubric_path.name}")
    print(f"  Judge calls: up to {len(pairs) * len(raters) * args.replicates}")
    print(f"  Output     : {output_dir}/")
    if done:
        print(f"  Resuming   : {len(done)} records already present")
    print()

    (output_dir / "run_config.json").write_text(
        json.dumps(
            {
                "phase": "rating",
                "sources": args.sources,
                "raters": raters,
                "replicates": args.replicates,
                "pairs_pooled": pooled_total,
                "pairs_used": len(pairs),
                "started": datetime.now(timezone.utc).isoformat(),
                **static_fields,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    totals: Dict[str, Dict[str, int]] = {}
    with open(records_path, "a", encoding="utf-8") as records_file:
        for label, model_str in raters.items():
            for replicate in range(1, args.replicates + 1):
                todo = [
                    p for p in pairs
                    if (p["pair_id"], label, replicate) not in done
                ]
                if not todo:
                    print(f"[{label} rep{replicate}] already complete, skipping")
                    continue
                stats = await rate(
                    label=label,
                    model_str=model_str,
                    replicate=replicate,
                    pairs=todo,
                    rubric=rubric,
                    principle=principle,
                    static_fields=static_fields,
                    records_file=records_file,
                    concurrency=args.concurrency,
                    chunk_size=args.chunk_size,
                    temperature=args.judge_temperature,
                    max_tokens=args.judge_max_tokens,
                    max_attempts=args.judge_attempts,
                )
                acc = totals.setdefault(label, {"scored": 0, "unscored": 0})
                acc["scored"] += stats["scored"]
                acc["unscored"] += stats["unscored"]

    print(f"\n{'=' * 60}")
    print("AGREEMENT PASS SUMMARY")
    print(f"{'=' * 60}")
    for label, acc in totals.items():
        print(f"  {label:14s} scored={acc['scored']:5d}  unscored={acc['unscored']:4d}")
    print(f"\nRecords: {records_path}")
    print()
    print("No statistics were computed. Unscored records carry score=null and a")
    print("judge_error; they are missing ratings, not low ones, and dropping them")
    print("silently would bias any agreement measure upward.")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    sys.exit(asyncio.run(main()))
