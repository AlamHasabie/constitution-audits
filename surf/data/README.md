# Local attribute files

Attribute files for `--attributes`. One JSON object per line. Only
`sae_attributes` is required and must be non-empty — rows without it are silently
skipped by the loader. `prompt` and `response` default to `""`.

```json
{"prompt": "...", "response": "...", "sae_attributes": ["...", "..."]}
```

Keep these files **ASCII-only**. `AttributeFileLoader._load_from_file` opens them
with a bare `open(path, "r")`, so the encoding comes from the locale and non-ASCII
content either mojibakes or raises on Windows (cp1252).

## `flourishing_datapath_attributes.jsonl`

20 attributes in 5 rows, for exercising the data path end to end without
downloading the 25k-row HuggingFace dataset.

```bash
uv run -m surf.cli.main run-em \
    --rubric rubrics/flourishing_full.yaml \
    --attributes data/flourishing_datapath_attributes.jsonl \
    --output-dir results/datapath \
    --target-model "openrouter:meta-llama/llama-3.1-8b-instruct" \
    --judge-model anthropic:claude-opus-4-5-20251101 \
    --iterations 1 --candidates 2 \
    --target-concurrency 1 --query-concurrency 1 --judge-concurrency 1
```

A working run writes `results/datapath/results.jsonl` with one line per scored
candidate, carrying `query`, `response`, `reward_score` and
`score_metadata.reasoning`. If those four are populated, the path works.

Attributes are grouped four to a row because `sample_attributes_for_candidate`
draws 1–5 attributes from a *single* row, then mixes them with replay-buffer
attributes and truncates at 5. Thematic grouping means any subset still reads as a
coherent description of one query, which is what `QUERY_GEN_PROMPT` expects.

### Not for measurement

These 20 attributes were written by hand. That makes them an auditor-chosen search
space — the same confound as putting worked examples in a rubric, moved one stage
upstream: the EM loop can only explore prompt categories the file contains, so
results describe whoever wrote the file as much as the model.

The default `seoirsem/CHUNKY-tulu3-SFT-25k-attributes` is derived from the Tulu-3
SFT mixture, so it approximates what users actually ask. Use it for anything you
intend to report, and do not compare numbers from this file against numbers from
that one. See [`../../methodology/flourishing_decision_log.md`](../../methodology/flourishing_decision_log.md).
