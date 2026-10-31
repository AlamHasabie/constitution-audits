# Withheld From the Judge

Material deliberately kept out of the SURF judge's prompt for the Flourishing audit.
It is archived rather than deleted so the decisions are reversible and auditable.

Nothing here is loaded by any code. `surf/run_persona.py` globs
`surf/rubrics/*_full.yaml`, non-recursively, so these files cannot be picked up as
live rubrics by accident.

| File | What it is |
|---|---|
| `flourishing_full.yaml` | The pre-stripping whole-constitution rubric: violation examples, severity band descriptions, false-positive guardrails, auditor notes |
| `flourishing_{candor,epistemic,charity,devotion,harm}.yaml` | The five per-section rubrics, before sectioning was abandoned |
| `flourishing_tenet_scenarios.md` | 15 testable behaviours (F1.1a–F5.1c) with probe scenarios and evaluation criteria, drafted as a tenet catalogue |

## Why each is here

- **The rubric content** was withheld because SURF's judge sits inside an optimiser:
  the EM loop maximises judge score, so examples steer the search rather than merely
  calibrating it. See
  [`../flourishing_decision_log.md`](../flourishing_decision_log.md) entry
  2026-10-29-B.
- **The section rubrics** were removed because section boundaries are an auditor's
  choice and would become a confound in the results. Entry 2026-10-29-A.
- **The tenet scenarios** were moved out of `tenets/` because nothing reads them and
  they have no `Sample` objects behind them, unlike
  [`tenets/anthropic_constitution.md`](../../tenets/anthropic_constitution.md), which
  mirrors a real eval dataset. The probe scenarios are genuine design work worth
  keeping — particularly the cases that put assertions in tension — so they are
  parked here as the draft for a future adjudication rubric.

The archived YAML files are byte-exact copies and are **not** edited to keep up with
the repo, so their header comments still reference paths as they were written — e.g.
`tenets/flourishing_constitution.md`, which now lives here as
`flourishing_tenet_scenarios.md`. That is deliberate: editing them would defeat the
point of a verbatim archive.

## Two stale things to know before reinstating anything

1. **Assertion numbering.** Every file here predates the 2026-10-29 correction from
   17 items to 15. Old numbers 2–17 correspond to new 1–15. Re-check against
   [`constitutions/flourishing_constitution.md`](../../constitutions/flourishing_constitution.md).
   The exception is `flourishing_tenet_scenarios.md`, which was renumbered before
   being moved here.
2. **Where it belongs.** If this material is reinstated, it belongs in an
   *adjudication* stage that runs on already-surfaced candidates, not in the search
   rubric. Putting it back into the search rubric changes which violations the loop
   finds and should be reported as a change to the measurement instrument.
