"""Dump worked examples from the Phase B validation, for qualitative analysis.

For each sampled case: the query, the full response, MiMo's score and reasoning, and
every rater's verdict, cited assertions, confidence, rationale and judge_error.

Cases are drawn at random within bucket under a fixed seed rather than chosen, so the
examples are not selected to support a reading. Change --seed to draw a different set;
--n for more per bucket.

    uv run analysis/phaseb_validation_samples.py
    uv run analysis/phaseb_validation_samples.py --n 5 --seed 7
"""
import argparse
import io
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_validation import build_cases, DEFAULT_ORIG, DEFAULT_NEW  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "results/phaseB_validation"
RECORDS = OUT / "records.jsonl"
BINARY = ("CONFIRMED", "FALSE_POSITIVE")


def majority(vs):
    v = [x for x in vs if x in BINARY]
    if not v:
        return "UNRESOLVED"
    c, f = v.count("CONFIRMED"), v.count("FALSE_POSITIVE")
    return "UNRESOLVED" if c == f else ("CONFIRMED" if c > f else "FALSE_POSITIVE")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3, help="cases per bucket (default 3)")
    ap.add_argument("--seed", type=int, default=20261109)
    ap.add_argument("--max-response-chars", type=int, default=0,
                    help="truncate responses to this many chars; 0 = full (default)")
    args = ap.parse_args()

    if not RECORDS.exists():
        sys.exit(f"no records at {RECORDS}")
    rows = [json.loads(l) for l in io.open(RECORDS, encoding="utf-8") if l.strip()]
    raters = sorted({r["rater_label"] for r in rows})

    # R2 supersedes R1 for the same (case, rater); keep both for display.
    per_round = defaultdict(dict)
    for r in rows:
        per_round[(r["case_id"], r["rater_label"])][r["round"]] = r
    final = {k: v.get(2) or v.get(1) for k, v in per_round.items()}

    src = {c["case_id"]: c for c in build_cases(DEFAULT_ORIG, DEFAULT_NEW, 15)}
    seen = {r["case_id"] for r in rows}

    # Human annotations, where the case happens to be one of the 30 in the pack.
    human = {}
    ann_path = OUT / "annotations.csv"
    if ann_path.exists():
        import csv
        for r in csv.DictReader(io.open(ann_path, encoding="utf-8")):
            cid = (r.get("case_id") or "").strip()
            v = (r.get("verdict") or "").strip().upper()
            if cid and v:
                human[cid] = {"verdict": v, "confidence": (r.get("confidence") or "").strip(),
                              "notes": (r.get("notes") or "").strip()}

    pool = defaultdict(list)
    for cid in sorted(seen):
        if cid not in src or src[cid]["stratum"] != "candidate":
            continue
        mv = majority([final[(cid, l)]["verdict"] for l in raters if (cid, l) in final])
        if mv in BINARY:
            pool[mv].append(cid)

    rng = random.Random(args.seed)
    picked = {b: rng.sample(sorted(pool[b]), min(args.n, len(pool[b]))) for b in BINARY}

    md = [
        "# Phase B validation — worked examples",
        "",
        f"Drawn at random within bucket, seed {args.seed}. "
        f"Pool sizes: majority-CONFIRMED {len(pool['CONFIRMED'])}, "
        f"majority-FALSE_POSITIVE {len(pool['FALSE_POSITIVE'])}. "
        "Sycophancy controls excluded.",
        "",
        "Selected at random rather than chosen, so these are not picked to support a "
        "reading. Re-run with a different `--seed` for another draw.",
        "",
    ]

    titles = {"CONFIRMED": "Majority-CONFIRMED — the panel upheld MiMo's flag",
              "FALSE_POSITIVE": "Majority-FALSE_POSITIVE — the panel rejected MiMo's flag"}

    for bucket in BINARY:
        md += [f"---", "", f"# {titles[bucket]}", ""]
        for i, cid in enumerate(picked[bucket], 1):
            c = src[cid]
            verdicts = {l: final[(cid, l)] for l in raters if (cid, l) in final}
            split = ", ".join(f"{l}={v['verdict']}" for l, v in sorted(verdicts.items()))
            resp = c["response"] or ""
            if args.max_response_chars and len(resp) > args.max_response_chars:
                resp = resp[:args.max_response_chars] + f"\n\n[... truncated, {len(c['response'])} chars total]"

            md += [
                f"## {bucket[:4].title()} {i} — `{cid}`",
                "",
                f"| | |",
                f"|---|---|",
                f"| arm | **{c['arm']}** |",
                f"| prompt_id | `{c['prompt_id']}` |",
                f"| MiMo score (flagging replicate) | **{c['judge_score']:.0f}** |",
                f"| MiMo max / median across 3 replicates | {c['max_score']:.0f} / {c['median_score']:.0f} |",
                f"| replicates straddle 50 | {'**yes**' if c['straddles_50'] else 'no'} |",
                f"| MiMo cited assertions | {c['judge_violated'] or 'none'} |",
                f"| panel | {split} |",
                f"| response length | {len(c['response'] or '')} chars |",
                "",
                "### Query",
                "",
                "```",
                (c["query"] or "").strip(),
                "```",
                "",
                "### Response",
                "",
                "```",
                resp.strip(),
                "```",
                "",
                "### MiMo's reasoning",
                "",
                "> " + (c["judge_reasoning"] or "(none recorded)").replace("\n", "\n> "),
                "",
                "### Rater reasoning",
                "",
            ]
            for lbl in raters:
                rec = verdicts.get(lbl)
                if not rec:
                    md += [f"**{lbl}** — no record", ""]
                    continue
                r1 = per_round[(cid, lbl)].get(1)
                md += [
                    f"**{lbl} — {rec['verdict']}** "
                    f"(confidence {rec.get('confidence')}, assertions {rec.get('assertions') or 'none'}"
                    + (f", decided in R{rec['round']}" if rec["round"] == 2 else "") + ")",
                    "",
                    "> " + (rec.get("rationale") or "(no rationale parsed)").replace("\n", "\n> "),
                    "",
                ]
                if rec.get("judge_error"):
                    md += ["> *What it says MiMo got wrong:* "
                           + rec["judge_error"].replace("\n", " "), ""]
                if rec["round"] == 2 and r1 and r1.get("rationale"):
                    md += [f"> *Its R1 verdict was {r1['verdict']}:* "
                           + r1["rationale"].replace("\n", " "), ""]

            if cid in human:
                h = human[cid]
                agree = "agrees with the panel" if h["verdict"] == bucket else \
                        ("**disagrees with the panel**" if h["verdict"] in BINARY
                         else "could not decide")
                md += [
                    "### Human annotation",
                    "",
                    f"This case was one of the 30 in the blind pack. The annotator "
                    f"{agree}.",
                    "",
                    f"**{h['verdict']}** (confidence {h['confidence'] or 'n/a'})",
                    "",
                    "> " + (h["notes"] or "(no note)").replace("\n", " "),
                    "",
                ]
            md += [""]

    path = OUT / "qualitative_samples.md"
    path.write_text("\n".join(md), encoding="utf-8")

    print(f"pool: CONFIRMED {len(pool['CONFIRMED'])}, FALSE_POSITIVE {len(pool['FALSE_POSITIVE'])}")
    for bucket in BINARY:
        print(f"\n{bucket}:")
        for cid in picked[bucket]:
            c = src[cid]
            vs = {l: final[(cid, l)]["verdict"] for l in raters if (cid, l) in final}
            unan = "unanimous" if len(set(vs.values())) == 1 else "split"
            print(f"  {cid}  arm={c['arm']:<11} judge={c['judge_score']:>3.0f}  "
                  f"straddle={'Y' if c['straddles_50'] else 'n'}  {unan:<9} "
                  f"resp={len(c['response'] or ''):>5}ch")
    print(f"\n  {path}")


if __name__ == "__main__":
    main()
