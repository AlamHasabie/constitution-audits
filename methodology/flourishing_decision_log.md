# Flourishing Audit: Decision Log

Dated record of methodology decisions for the Flourishing persona audit — what was
decided, why, what it changed, and whether it has been validated yet. Newest first.

Entry IDs are `YYYY-MM-DD-X` so they sort chronologically and can be cited from
reports. Grep a date to see what changed that day:

```bash
grep -n "^## 2026-10-29" methodology/flourishing_decision_log.md
```

## Index

| Entry | Date | Decision | Status |
|---|---|---|---|
| [2026-10-31-A](#2026-10-31-a--generated-rubrics-and-one-runner-per-persona) | 2026-10-31 | Rubrics generated, not hand-written; one runner per persona | **Verified** reproducible |
| [2026-10-29-C](#2026-10-29-c--constitution-has-15-items-not-17) | 2026-10-29 | Constitution has 15 items, not 17 | **Verified** against source |
| [2026-10-29-B](#2026-10-29-b--severity-by-score-range-only-no-examples) | 2026-10-29 | Severity by score range only, no examples | Unvalidated — mechanism not built |
| [2026-10-29-A](#2026-10-29-a--no-dissection-of-the-constitution) | 2026-10-29 | No dissection of the constitution | Unvalidated — no sweep run |
| [2026-10-27-B](#2026-10-27-b--whole-constitution-rubric-made-the-default) | 2026-10-27 | Whole-constitution rubric made the default | Superseded by 2026-10-29-A |
| [2026-10-27-A](#2026-10-27-a--initial-scaffold) | 2026-10-27 | Initial scaffold, sectioned into five rubrics | Reversed by 2026-10-27-B |

**Nothing in this log has been validated against a live model.** No sweep has been
run. Every "works well" claim below is confined to what was mechanically verified
(files load, counts match the source); no claim is made about measurement quality.

---

## 2026-10-31-A — Generated rubrics and one runner per persona

**Decision.** Changed rubrics from hand-written to **generated** from their
constitution file by
[`../surf/utils/make_persona_rubric.py`](../surf/utils/make_persona_rubric.py), and
generalised the runner from `run_flourishing.py` to
[`../surf/run_persona.py`](../surf/run_persona.py) with `--persona`.

**Why generate.** The rubric *is* the measurement instrument, so it should be
reproducible from its source and diffable against it rather than typed out once and
trusted. `--check` regenerates and exits non-zero on drift, which catches both an
edited rubric and a changed constitution. It also makes adding any of the remaining
nine personas a three-step job: write the constitution file, generate, sweep.

**Why one runner.** Copying `run_flourishing.py` per persona would have reproduced
the duplication this repo already suffers from in `run_tenets.py`, where section
rubrics live as Python dicts and the README's advertised YAML files do not exist.
Personas are discovered from `rubrics/*_full.yaml`, so the runner needs no edit when
one is added. The `--rubrics` and `--all-sections` flags are gone, having been dead
since the per-section rubrics were removed on 2026-10-29.

**Status: verified reproducible.** The Flourishing rubric regenerates
byte-identically from its constitution (`--check` passes). The switch to generation
changed 13 comment lines and left the judge-visible text byte-identical at 1954
characters, confirmed before the rewrite, so it did not touch the measurement.

**Scaffolded and withdrawn the same day: the Loving persona.** A second persona
(Loving, 10 assertions, item boundaries verified against the arXiv HTML) was
scaffolded and then removed at the user's request before any sweep. Recorded because
the reasoning is worth keeping: Loving is a **near-inverse** of Flourishing — it
asserts the model should validate feelings and avoid harshness or judgment, where
Flourishing asserts it should tell hard truths and refuse middle views. A
Loving-trained model should therefore score high on the Flourishing rubric and low on
the Loving one, which would have operationalised the cross-persona control listed as
the top open item below. That control still needs two *trained models*, not just two
rubrics, so nothing measurable was lost by withdrawing it.

Also worth keeping: Loving would have been the harder persona to audit, because its
assertions describe *tone* — "subtly", "gently", "softly" recur with no behavioural
test attached. Expect any tone-based persona to produce lower judge agreement than
Flourishing's comparatively crisp conditions like "help with the legal
interpretation".

---

## 2026-10-29-C — Constitution has 15 items, not 17

**Decision.** The Flourishing constitution contains 15 assertions. An earlier reading
of 17 was wrong and every downstream reference was renumbered.

**Why.** Items in an Open Character Training constitution may span several sentences.
The "People of good character..." item is three sentences in a single bullet; the next
bullet marker does not appear until "I try to avoid adopting 'middle' views." An
earlier transcription split it into three, inflating the count.

**Root cause, worth recording.** The text was extracted from the arXiv HTML through
an automated summarizer with a ~125-character quote limit, which broke long bullets at
quote boundaries. Three such splits were spotted and rejoined; the one at item 1 was
not. The failure was treating a known-unreliable source as reliable after patching
the instances that happened to be noticed, rather than distrusting the extraction
method as a whole.

**What changed.** `constitutions/flourishing_constitution.md` rewritten to 15 items
with a format note that sentence count is not item count. All 15 line references in
the tenet draft remapped in a single pass; prose assertion numbers updated; the
rubric regenerated from the corrected source. Old numbers 2–17 map to new 1–15.

**Status: verified.** Item boundaries re-checked against the arXiv HTML. All 15
assertions confirmed present in the rubric verbatim by whitespace-normalised
comparison against the constitution file.

**What would change it.** The PDF rendering differing from the HTML. The verification
note in the constitution file flags that typography was not checked against the PDF.

---

## 2026-10-29-B — Severity by score range only, no examples

**Decision.** The rubric states the 0–100 range and that >50 indicates a violation,
and says nothing else about severity. No band descriptions, no worked violation
examples, no false-positive guardrails, no auditor notes. Consistency is to come from
a multi-rater adjudication stage instead.

**Why.** Two separate reasons, and the second is the stronger one.

1. *Provenance.* The constitution states no priority ordering and has no notion of
   severity, so any severity scale or worked example is supplied by the auditor.
   Including them makes the measurement partly report the auditor's taxonomy.

2. *Goodhart.* SURF's judge sits inside an optimiser — the EM loop maximises judge
   score. Examples therefore do not merely calibrate the judge, they **steer the
   search**. A rubric naming derivative poetry as a sycophancy example pulls the loop
   toward creative-feedback prompts, and the result is coverage of the neighbourhood
   of the auditor's guesses reported as coverage of the constitution. Outside a
   search loop examples are nearly free; inside one they are a prior on where you
   look.

**Accepted cost.** Higher judge variance, and the loss of guardrails that suppressed
known artifacts (garbled prompts, justified refusals, contrarianism, warmth without
sycophancy). The position is that variance is measurable and correctable downstream
whereas a steered search is neither.

**Consequence for reporting.** Scores from this stage are a **ranking signal** for
surfacing candidates, not a measurement. Absolute scores should not be reported.

**What changed.** The rubric went from 10,885 to 1,954 characters of judge
instruction. Withheld text archived verbatim under
[`withheld_from_judge/`](withheld_from_judge). Rationale and the planned adjudication
design in [`flourishing_rubric_minimalism.md`](flourishing_rubric_minimalism.md).

**Not fully achieved.** `surf/em_loop/prompts.py:OPUS_DIRECT_SCORE_PROMPT` injects
band labels (NO / MODERATE / SIGNIFICANT / SEVERE) and its own guardrails into every
judge call regardless of rubric. The judge is less anchored, not unanchored. Removing
that would change the instrument for `rebuttal.yaml` and `soul_doc_overcaution.yaml`
too, including runs behind already-published results, so it was left alone.

**Status: unvalidated, and the mechanism it depends on does not exist.** The
multi-rater adjudication stage is designed but not built. Until it is, this decision
has removed calibration without yet supplying the replacement — the known weak point
of the current setup.

**What would change it.** Intra-rater self-agreement turning out so low that the
scale is unusable at this granularity, which would argue for a coarser scale rather
than restoring examples. Or the cross-persona control failing, which would mean the
rubric cannot separate personas at all and the examples were doing load-bearing work.

---

## 2026-10-29-A — No dissection of the constitution

**Decision.** One rubric, scoring all 15 assertions together. No division into
sections or per-assertion rubrics. The five per-section rubrics created on 2026-10-27
were deleted.

**Why.** Dividing a constitution is an opinionated act — there are many defensible
divisions and the constitution states none — so if sections are the measurement unit,
every violation's section label is an artifact of the auditor's taxonomy rather than a
property of the model. A concrete instance from the deleted scheme: it placed
"provide factual information about risky activities" (assertion 5) and "avoid causing
any harm" (assertion 13) in different sections, so one coherent model behaviour
registered as a hit in one bucket and a miss in another.

The Anthropic soul doc is sectioned in this repo out of necessity — 205 tenets is far
past what one rubric can hold. Flourishing is 15 short assertions and fits whole, so
the confound buys nothing.

**Known tradeoff.** SURF's EM loop converges on whichever failure mode scores
highest, so one combined rubric explores the **loudest** signal rather than all of
them. The intended remedy is iterative ablation — run, inspect the buffer, exclude
what dominated, re-run — which keeps the measurement whole-constitution across
iterations instead of dividing it up front. This is the workflow the repo's existing
combined rubrics already use.

**Status: unvalidated.** No sweep has been run, so it is not known how many
iterations the ablation loop needs to cover the constitution, or whether one failure
mode dominates so strongly that the approach is impractical.

**What would change it.** Ablation proving too slow or too expensive to reach beyond
the first one or two failure modes. The fallback would be per-assertion rubrics
(15 of them, one per published item) rather than a return to auditor-chosen sections —
per-assertion division is at least the constitution's own structure.

---

## 2026-10-27-B — Whole-constitution rubric made the default

Superseded by [2026-10-29-A](#2026-10-29-a--no-dissection-of-the-constitution), which
removed the section rubrics entirely. On this date the whole-constitution rubric was
added and made the default while the five section rubrics were kept as opt-in
drill-down. Reasoning as in 2026-10-29-A; the only change since is that the sections
are now gone rather than optional.

---

## 2026-10-27-A — Initial scaffold

**What was built.** The Flourishing constitution transcribed from the paper
(incorrectly, as 17 items — see 2026-10-29-C); a 15-tenet draft of testable
behaviours; five per-section SURF rubrics; and `surf/run_flourishing.py`, which
discovers rubrics from filenames rather than carrying them inline as the repo's other
runners do.

**Sectioning rationale at the time, and why it was wrong.** The constitution was
divided into five sections to match the repo's existing convention — the soul doc has
205 tenets across 17 sections and `run_tenets.py` exposes five section rubrics. That
is a reason about this codebase's conventions, not about Flourishing, and it was not
checked against whether the convention transfers to a 15-assertion spec. It does not.
Reversed two days later.

**Incidental bug found and fixed.** `surf/em_loop/judge.py:load_rubric` opened rubric
files with no encoding argument, so on Windows (cp1252) `rubrics/rebuttal.yaml` could
not be loaded at all — a hard `UnicodeDecodeError` on a subscript character — and
other rubrics silently mojibaked their em dashes into the judge prompt. Fixing the
read required fixing the write side too, since the four `run_*.py` scripts dump
`rubric.yaml` with the same locale default. Both ends now specify UTF-8.

**Status: verified.** All rubrics in the repo now load, including `rebuttal.yaml`,
which previously raised. Write-then-read round trip confirmed with non-ASCII content.
This is the one entry in this log with a demonstrated improvement, and it is an
infrastructure fix rather than a methodology result.

---

## Open, in priority order

1. **Cross-persona control.** Run the rubric against models trained on the paper's
   Sycophantic and Misaligned personas as known positives and Flourishing as a known
   negative. If it cannot separate them, the rubric is broken regardless of any
   reliability statistic. Needs no criteria, so it does not depend on anything else
   here, which is why it is first.
2. **Intra-rater ceiling.** Re-rate a sample with the same judge. `judge.py` pins
   `temperature=1.0`, so self-inconsistency is non-zero by construction. This bounds
   achievable inter-rater agreement and is cheap.
3. **Multi-rater adjudication.** Design in
   [`flourishing_rubric_minimalism.md`](flourishing_rubric_minimalism.md). Fix the
   anchoring and correlated-error flaws in the existing validation pipeline first.
4. **First real sweep**, after the above, so the results are interpretable.
