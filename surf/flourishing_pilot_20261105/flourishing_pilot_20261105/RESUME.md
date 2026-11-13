# Flourishing SURF pilot — archive, 2026-11-05

Everything produced on the GPU pod. **No GPU is needed for what remains.**

## What is in here

| Path | What |
|---|---|
| `surf/results/phaseA_{base,flourishing,sycophancy}/` | Phase A searches, 75/72/70 candidates |
| `surf/results/phaseB/` | **the primary measurement** — 651 records, 217 prompts x 3 arms |
| `surf/results/agreement_1/` | the earlier judge-agreement run (2026-11-04-A) |
| `surf/results/phaseA_{flash,tulu}/` | the earlier judge-calibration searches |
| `surf/results/smoke_20261105/` | smoke test that verified the temperature patch |
| `surf/results/*/run_config.json` | per-run provenance: models, sampling, rubric sha, git commit |
| `notes/SURF_FLOURISHING_RUNBOOK.md` | the runbook and every result written up |
| `methodology/flourishing_decision_log.md` | includes the new entry 2026-11-05-A |
| `surf/analysis/discrimination.py` | the Phase B analysis, re-runnable |
| `surf/scripts/` | adapter download, vLLM launcher, target checks |
| `surf/rubrics/flourishing_banded.yaml` | the rubric **as run**, verbatim |
| `constitutions/flourishing_constitution.md` | the rubric's source |
| `code_changes.patch` | the source edits, uncommitted — `git apply` it |
| `vllm_serve.log` | startup log, evidences the sampling override |

**No `.env` and no API keys.** `surf/.env.example` documents which variables are
needed. Adapters and model weights are excluded — re-downloadable with
`surf/scripts/fetch_persona_adapters.py`.

## State of the pilot

Done: Phase A (3 arms), Phase B (primary), the discrimination analysis.

| check | result | spec threshold | verdict |
|---|---|---|---|
| sycophancy vs base | AUC 0.919 | >= 0.8 usable | pass |
| sycophancy vs flourishing | AUC 0.827 | >= 0.8 usable | pass |
| **flourishing vs base** | **AUC 0.598, wrong direction** | >= 0.8 usable, < 0.65 rework | **fail** |

The flourishing-trained model scores as violating its own constitution *more* than
the untrained base (paired sign test p = 0.0014, n = 194). Robust to origin stratum
and to excluding the severe band and assertions 1 and 15. Full reasoning and the two
competing interpretations are in the runbook's Phase B section.

## What is left, none of it needing a GPU

1. **Human spot-check of flourishing's 29 *significant* records.** This is the
   decisive step — it decides whether the failure above is a real finding about
   persona training or a broken instrument. Read transcripts, not numbers.
2. **Re-score the 48 unscored records.** Judge parse failures are non-uniform across
   arms (4.6% / 6.5% / 11.1%), so excluding them may bias the comparison.
3. **Write `analysis/agreement.py`** — the stratified sampler and the statistics.
   Fix the sampling plan in code *before* looking at scores. Does not exist yet.
4. **Agreement study** — `run_rater.py`, k=5 replicates, plus a cross-family rater.
   Needs `ANTHROPIC_API_KEY`; the pilot spec requires a different model family from
   the primary judge.
5. **`analysis/coviolation.py`** — the 15x15 matrix, to test the provisional clusters.

Steps 2 and 4 call judges over saved `(query, response)` pairs and no target model, so
they are API calls plus these JSONL files. Step 1 is reading. Steps 3 and 5 are CPU.

## Resuming

```bash
git clone -b feat/open-character-model-training-audit https://github.com/AlamHasabie/constitution-audits.git
cd constitution-audits
git apply /path/to/code_changes.patch
cp -r /path/to/archive/surf/results surf/
cp -r /path/to/archive/notes .
cd surf && uv sync          # no --extra vllm needed
cp .env.example .env        # fill MODEL_API_KEY and ANTHROPIC_API_KEY
uv run analysis/discrimination.py results/phaseB/records.jsonl
```
