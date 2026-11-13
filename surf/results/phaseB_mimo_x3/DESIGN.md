# MiMo ×3 over Phase B — design and pre-registered analysis

Written before any records landed. The point of fixing it in advance is that
this session has already produced one result I read the wrong way round
(decision 2026-11-05-B), and the headline here is a +6.98 effect against a judge
whose replicate spread reached 46 points. Deciding afterwards what counts as
confirmation is how that goes wrong twice.

## Question

Does the Phase B flourishing-vs-base gap survive averaging out judge noise?
Secondary: what is MiMo's self-consistency on this rubric, and how many of the
48 unscored rows come back?

## Design

| | |
|---|---|
| Pairs | **all 651** Phase B (query, response) pairs |
| Replicates | 3 |
| Attempts | **1** — retries hide the failure rate, which is one of the measurements |
| Judge | `XiaomiMiMo/MiMo-V2.6-Flash` via DeepInfra, thinking off |
| Temperature | 1.0 (decision 2026-11-05-B; 0.2 measured 85% failure) |
| max_tokens | 2048 |
| Rubric | `rubrics/flourishing_banded.yaml`, unchanged from Phase B |
| Calls | 1,953 |

**Why all 651 and not the 543 belonging to the 181 complete prompts.** The extra
108 pairs are the ones from the 36 prompts that lost an arm to judge failure.
Including them costs 324 calls (+20%) and folds the recovery question into the
same balanced pass, so every Phase B row ends up with the same three ratings
instead of two populations measured differently. `--limit` takes a prefix of the
pair_id sort, not a filter, so excluding them would have meant building a
separate input file for no benefit.

## Pre-registered analysis

**Aggregation.** Per pair, the **median** of its available scored replicates.
Median not mean: the failure mode here is a wild outlier, not Gaussian noise.
A pair with zero scored replicates stays unscored.

**Primary outcome.** Paired flourishing − base delta over prompts where all three
arms have at least one scored replicate, with a bootstrap 95% CI and a Wilcoxon
signed-rank test, computed exactly as in the current report.

- CI **excludes 0** and the sign is positive → the §5 finding stands, with judge
  noise now averaged down rather than assumed away.
- CI **includes 0** → the headline weakens to "no difference detectable once the
  judge is replicated", and both §4b and §5 of
  `validation_reports/surf_flourishing_phaseB.md` must be rewritten, not
  footnoted.
- Sign **reverses** → the original result was noise and the report is withdrawn.

**Intra-judge consistency.** Per-pair standard deviation and range across the 3
replicates; report the median and the upper tail, and the share of pairs whose
replicates straddle the 50 threshold (those are the ones where a single rating
decides the violation flag). Compare against the 46-point max spread recorded in
`agreement_1` (decision 2026-11-04-A).

**Assertion 4.** Re-count on median-aggregated ratings. The claim under test is
the 15-vs-1 contrast against base, not the absolute count.

**The 40 high-scoring prompts — descriptive only.** Their shrinkage **will not be
treated as evidence** about whether the effect is real. They were selected on
their own score, so regression to the mean guarantees shrinkage in every world.
Reported for completeness and explicitly labelled uninterpretable as a test.

**Recovery.** Of the 48 rows previously unscored, how many get ≥1 scored
replicate in 3 tries. The naive independent prediction is ~99.96% recovery at a
7.4% per-call failure rate; failures are known to cluster by prompt (12 prompts
lost 2 arms where independence predicts 3.5), so a materially lower figure is the
expected outcome and is itself the finding.

## Caveat fixed in advance

Three replicates averages judge *noise*. It does nothing about judge *bias*: if
MiMo systematically penalises terse refusals, all three replicates do so together
and the delta survives for the wrong reason. Only a second rater or a human read
addresses that, and neither is in this run.
