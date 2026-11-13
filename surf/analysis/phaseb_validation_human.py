"""Score the human annotations against the rater panel.

The analysis fixed in results/phaseB_validation/DESIGN.md: raw agreement per
bucket and the full 2x2, with kappa only where the marginals can carry it.

    uv run analysis/phaseb_validation_human.py
"""
import csv
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "results/phaseB_validation"
BINARY = ("CONFIRMED", "FALSE_POSITIVE")


def kappa(a, b):
    n = len(a)
    if n == 0:
        return float("nan")
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa = sum(1 for x in a if x == "CONFIRMED") / n
    pb = sum(1 for x in b if x == "CONFIRMED") / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return float("nan") if pe in (0.0, 1.0) else (po - pe) / (1 - pe)


def confusion(human, rater, label):
    """2x2 with the human on rows. a = both confirmed, d = both FP."""
    pairs = list(zip(human, rater))
    a = sum(1 for h, r in pairs if h == "CONFIRMED" and r == "CONFIRMED")
    b = sum(1 for h, r in pairs if h == "CONFIRMED" and r == "FALSE_POSITIVE")
    c = sum(1 for h, r in pairs if h == "FALSE_POSITIVE" and r == "CONFIRMED")
    d = sum(1 for h, r in pairs if h == "FALSE_POSITIVE" and r == "FALSE_POSITIVE")
    n = a + b + c + d
    print(f"\n  {label}  (n={n})")
    print(f"                      {'rater CONF':>12}{'rater FP':>10}")
    print(f"    human CONFIRMED   {a:>12}{b:>10}")
    print(f"    human FP          {c:>12}{d:>10}")
    if n:
        print(f"    raw agreement {(a+d)}/{n} = {(a+d)/n*100:.0f}%   kappa {kappa(human, rater):.2f}")
        print(f"    rater rejects what human confirms: {b}    rater confirms what human rejects: {c}")
    return a, b, c, d


def main():
    key_path = OUT / "annotation_key.json"
    ann_path = OUT / "annotations.csv"
    for p in (key_path, ann_path):
        if not p.exists():
            sys.exit(f"missing {p}")

    key = json.loads(io.open(key_path, encoding="utf-8").read())
    cases = key["cases"]
    raters = key["raters"]

    rows = list(csv.DictReader(io.open(ann_path, encoding="utf-8")))
    ann = {}
    for r in rows:
        cid = (r["case_id"] or "").strip()
        if not cid:
            continue
        v = (r["verdict"] or "").strip().upper().replace(" ", "_")
        conf = (r["confidence"] or "").strip()
        ann[cid] = {"verdict": v, "confidence": int(conf) if conf.isdigit() else None,
                    "notes": (r["notes"] or "").strip()}

    print("=" * 78)
    print("HUMAN ANCHOR vs RATER PANEL")
    print("=" * 78)
    print(f"cases in pack {len(cases)}   annotated {sum(1 for v in ann.values() if v['verdict'])}")

    # ---- 1. completion, and where UNSURE landed -------------------------
    print("\n" + "=" * 78)
    print("1. COMPLETION, AND WHERE 'UNSURE' LANDED")
    print("=" * 78)
    counts = Counter(v["verdict"] for v in ann.values())
    for k in sorted(counts):
        print(f"  {k or '(blank)':<18}{counts[k]:>4}")

    usable = [cid for cid in cases if ann.get(cid, {}).get("verdict") in BINARY]
    unsure = [cid for cid in cases if ann.get(cid, {}).get("verdict") not in BINARY]
    print(f"\nusable for agreement: {len(usable)} of {len(cases)}")

    print("\nUNSURE by the bucket the case was sampled from -- this is the number that")
    print("decides whether the agreement estimate is balanced or not:")
    by_bucket = defaultdict(lambda: [0, 0])
    for cid in cases:
        b = cases[cid]["majority"]
        by_bucket[b][0 if cid in usable else 1] += 1
    print(f"  {'sampled bucket':<22}{'usable':>8}{'unsure':>8}")
    for b in sorted(by_bucket):
        print(f"  majority-{b:<13}{by_bucket[b][0]:>8}{by_bucket[b][1]:>8}")

    print("\nUNSURE by arm (sealed-key info):")
    arms = defaultdict(lambda: [0, 0])
    for cid in cases:
        a = cases[cid]["arm"]
        arms[a][0 if cid in usable else 1] += 1
    for a in sorted(arms):
        print(f"  {a:<22}{arms[a][0]:>8}{arms[a][1]:>8}")

    print("\nstated reasons for UNSURE:")
    for cid in unsure:
        note = ann.get(cid, {}).get("notes", "")
        print(f"  {cid}  {note[:70]}")

    if not usable:
        sys.exit("\nno usable binary annotations -- nothing to score")

    # ---- 2. the comparison ----------------------------------------------
    print("\n" + "=" * 78)
    print("2. AGREEMENT")
    print("=" * 78)
    human = [ann[cid]["verdict"] for cid in usable]
    hc = human.count("CONFIRMED")
    print(f"human on the usable {len(usable)}: CONFIRMED {hc}, FALSE_POSITIVE {len(human)-hc}"
          f"  ({hc/len(human)*100:.0f}% confirmed)")
    maj = [cases[cid]["majority"] for cid in usable]
    mc = maj.count("CONFIRMED")
    print(f"panel majority on the same {len(usable)}: CONFIRMED {mc}, FALSE_POSITIVE {len(maj)-mc}"
          f"  ({mc/len(maj)*100:.0f}% confirmed)")

    confusion(human, maj, "human vs MAJORITY VOTE")
    for lbl in raters:
        rv = [cases[cid]["rater_verdicts"].get(lbl, "UNRESOLVED") for cid in usable]
        keep = [i for i, v in enumerate(rv) if v in BINARY]
        if not keep:
            continue
        confusion([human[i] for i in keep], [rv[i] for i in keep], f"human vs {lbl}")

    # ---- 3. confidence --------------------------------------------------
    print("\n" + "=" * 78)
    print("3. HUMAN CONFIDENCE, AGREEMENT vs DISAGREEMENT")
    print("=" * 78)
    agree_c, dis_c = [], []
    for cid in usable:
        c = ann[cid]["confidence"]
        if c is None:
            continue
        (agree_c if ann[cid]["verdict"] == cases[cid]["majority"] else dis_c).append(c)
    for name, xs in (("agreed with majority", agree_c), ("disagreed", dis_c)):
        if xs:
            print(f"  {name:<24}n={len(xs):<4} mean confidence {sum(xs)/len(xs):.1f}")
    print("\nIf disagreements carry LOW human confidence they are noise; if they carry")
    print("HIGH confidence the panel is wrong in a patterned way.")

    # ---- 4. descriptive -------------------------------------------------
    print("\n" + "=" * 78)
    print("4. DESCRIPTIVE ONLY (tiny n -- not a contrast)")
    print("=" * 78)
    print(f"  {'arm':<14}{'usable':>8}{'human conf':>12}{'panel conf':>12}")
    for a in sorted(arms):
        ids = [cid for cid in usable if cases[cid]["arm"] == a]
        if not ids:
            continue
        h = sum(1 for cid in ids if ann[cid]["verdict"] == "CONFIRMED")
        m = sum(1 for cid in ids if cases[cid]["majority"] == "CONFIRMED")
        print(f"  {a:<14}{len(ids):>8}{h:>12}{m:>12}")
    print("\nThe pack was sampled by verdict bucket, not by arm, so these columns are")
    print("not a base/flourishing comparison and must not be read as one.")


if __name__ == "__main__":
    main()
