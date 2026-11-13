# Judge temperature sweep — design

Fixing the design here before the numbers are visible, so the reading of them is
not chosen after the fact.

## Question

Does MiMo-V2.6-Flash have a workable judge temperature below 1.0, and does the
score it returns shift systematically with temperature?

This follows decision 2026-11-05-B, where lowering the default to 0.2 was
reverted after measuring 85.1% no-score against 7.4% at 1.0. That measurement
compared two different prompt samples, so this one is paired.

## Design

| | |
|---|---|
| Pairs | 60, the first by `pair_id` from the 651 phase B pairs |
| Temperatures | 0.2, 0.4, 0.6, 0.8, 1.0 |
| Replicates | 1 |
| Attempts | **1** — retries hide the failure rate, which is the measurement |
| Judge | `XiaomiMiMo/MiMo-V2.6-Flash` via DeepInfra, thinking off |
| Rubric | `rubrics/flourishing_banded.yaml` |
| Calls | 300 |

**Paired.** `run_rater.py` sorts by `pair_id` before applying `--limit`, so all
five runs see the identical 60 pairs. `pair_id` is a sha256 of the normalised
(query, response), so selecting the lowest 60 is arbitrary with respect to score
but fixed — not a sample drawn after seeing results.

**Sample composition**, confirmed before launching:

- arms: base 25, flourishing 15, sycophancy 20
- bands: none 25, no_low 7, moderate 13, significant 11, (severe 0 — only 8 exist
  in the whole pool), plus 4 with no score
- the 4 unscored are 6.7% of the sample against 7.4% of the pool, so the sample
  is not enriched for failures
- scores at 1.0 span 3–78, mean 36.1

So a temperature that broke only on hard prompts, or only on one arm, would still
be visible.

## What each outcome means

- **Failure rate flat and low from 0.4 up** — 1.0 is not special, and a lower
  temperature is available if wanted for variance.
- **Failure rate climbing as temperature falls** — confirms no usable
  low-temperature regime; 1.0 stays, and retries remain the only mitigation.
- **Rate fine but scores drifting with temperature** — temperature is a
  calibration knob, not just a noise knob, and every comparison must hold it
  fixed. This would be the most consequential outcome, because the pilot's
  arm comparison would then depend on a setting nobody had chosen deliberately.

`origin_score` on each record carries that pair's original 1.0 score, so drift is
readable without a join.

## Caveat

n=60 per temperature. The standard error on a rate near 10% is about 4 points, so
this can separate 7% from 85% decisively and 7% from 12% not at all. It is a
screen for a broken regime, not a calibration.
