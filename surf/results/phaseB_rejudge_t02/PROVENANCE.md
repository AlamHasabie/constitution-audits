# Provenance: phaseB_rejudge_t02

Re-judge of the 2026-11-05 phase B responses at judge temperature 0.2.

## What produced it

| | |
|---|---|
| Input | `surf/flourishing_pilot_20261105/.../surf/results/phaseB/records.jsonl` (651 rows, 651 distinct pairs) |
| Judge | `XiaomiMiMo/MiMo-V2.6-Flash` via DeepInfra, thinking off |
| Rubric | `rubrics/flourishing_banded.yaml` |
| Sampling | temperature 0.2, max_tokens 1024, **attempts 1** |
| Replicates | 3 |

## The commit the records point at is not the code that ran

The run started before the judge change was committed, so every record
carries `git_commit: 84f86ed` with `git_dirty: true`. The code that actually
ran is:

    8b45803  fix: unpin judge sampling temperature and retry unparsed verdicts

`judge_code_changes.patch` in this directory is that diff as captured at launch,
against the base commit in `judge_code_base_commit.txt`. Applying the patch to
84f86ed reproduces the code that produced these records; so does checking out
8b45803.

## Why attempts=1, when the new default is 3

Retries are right for a scoring run and wrong for measuring the judge. With
attempts=3 each replicate is a best-of-3, which hides the collapse rate -- the
number this run exists to compare against the 7.4% observed at temperature 1.0 --
and conditions every replicate on having parsed, which is the wrong input to a
self-consistency measure. At attempts=1 each replicate is an independent draw,
and a pair is only lost if all three fail.

## Reading the output

Records are `phase: "rating"`, so arm identity is not in them: `pool_pairs` keys
on `(query, response)` and drops `target_label`, leaving `pair_origin: phaseB`
for all three arms. Rejoin on `pair_id`, which is a deterministic
sha256 of the normalised pair, against the phase B records.

`origin_score` carries each pair's temperature-1.0 score (null for the 48 that
failed then), so the 1.0-vs-0.2 drift is readable without a join.

Scores here are **not comparable** with the phase A buffer scores or the
original phase B numbers: those were taken at judge temperature 1.0, and
judge temperature is part of the instrument (decision 2026-11-05-B).
