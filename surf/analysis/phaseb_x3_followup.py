"""Apples-to-apples checks on the x3 pass: same-181 delta, assertion significance."""
import hashlib
import io
import json
import re
import sys
from collections import Counter, defaultdict

import numpy as np
from scipy import stats

_WS = re.compile(r"\s+")
ARMS = ["base", "flourishing", "sycophancy"]


def norm(t):
    return _WS.sub(" ", (t or "").strip().lower())


def pid_of(q, r):
    return hashlib.sha256((norm(q) + "\x00" + norm(r)).encode("utf-8")).hexdigest()[:16]


def load(p):
    return [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]


orig = load(sys.argv[1])
new = load(sys.argv[2])

meta = {}
for r in orig:
    meta[pid_of(r["query"], r["response"])] = {
        "prompt_id": r["prompt_id"], "arm": r["target_label"],
        "orig_score": r.get("score"), "orig_violated": r.get("violated") or [],
        "prompt_origin": r.get("prompt_origin")}

reps = defaultdict(list)
for r in new:
    reps[r["pair_id"]].append(r)

agg = {}
for p, rs in reps.items():
    sc = [r["score"] for r in rs if r.get("score") is not None]
    agg[p] = {"median": float(np.median(sc)), "all": rs, "n": len(sc)} if sc else None

bp = defaultdict(dict)
for p, m in meta.items():
    bp[m["prompt_id"]][m["arm"]] = p

orig181 = sorted(p for p in bp
                 if all(a in bp[p] and meta[bp[p][a]]["orig_score"] is not None
                        for a in ARMS))
x3_214 = sorted(p for p in bp
                if all(a in bp[p] and agg.get(bp[p][a]) for a in ARMS))
both = sorted(set(orig181) & set(x3_214))

print("original complete : %d" % len(orig181))
print("x3 complete       : %d" % len(x3_214))
print("intersection      : %d" % len(both))
print()


def paired(vals_x, vals_y, label):
    x, y = np.array(vals_x, float), np.array(vals_y, float)
    d = y - x
    w = stats.wilcoxon(y, x, zero_method="wilcox")
    boot = np.array([np.random.default_rng(s).choice(d, len(d), replace=True).mean()
                     for s in range(4000)])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    print("%-46s n=%3d  %+6.2f  CI [%+.2f, %+.2f]  p=%.2e"
          % (label, len(d), d.mean(), lo, hi, w.pvalue))
    return d.mean(), lo, hi


print("=" * 78)
print("APPLES TO APPLES: flourishing - base, same prompts, different ratings")
print("=" * 78)
paired([meta[bp[p]["base"]]["orig_score"] for p in orig181],
       [meta[bp[p]["flourishing"]]["orig_score"] for p in orig181],
       "ORIGINAL ratings, original 181 prompts")
paired([agg[bp[p]["base"]]["median"] for p in both],
       [agg[bp[p]["flourishing"]]["median"] for p in both],
       "x3 median ratings, SAME 181 prompts")
paired([agg[bp[p]["base"]]["median"] for p in x3_214],
       [agg[bp[p]["flourishing"]]["median"] for p in x3_214],
       "x3 median ratings, all 214 x3-complete prompts")
print()
print("The middle row is the only like-for-like test of 'does the effect survive")
print("replicating the judge': same prompts, judge noise averaged down.")

print()
print("=" * 78)
print("ASSERTION CONTRASTS -- is the weakened item 4 still a real contrast?")
print("=" * 78)


def counts(prompts, mode):
    out = {a: Counter() for a in ARMS}
    for p in prompts:
        for a in ARMS:
            v = agg[bp[p][a]]
            c, ns = Counter(), 0
            for r in v["all"]:
                if r.get("score") is None:
                    continue
                ns += 1
                for i in set(r.get("violated") or []):
                    c[i] += 1
            items = ([i for i, k in c.items() if k * 2 > ns] if mode == "majority"
                     else list(c))
            for i in set(items):
                out[a][i] += 1
    return out


cc = counts(x3_214, "majority")
N = len(x3_214)
print("majority-vote attributions over %d prompts" % N)
print()
print("%-5s %-44s %6s %7s %9s" % ("item", "assertion (abbrev)", "base", "flour", "Fisher p"))
LAB = {1: "likable != good character", 2: "avoids 'middle' views",
       3: "sees many perspectives", 4: "assumes the legal reading",
       5: "factual info on risky topics", 6: "interprets queries charitably",
       7: "loves humanity", 13: "avoids causing harm", 14: "promotes human welfare",
       15: "does what is best for humanity"}
for k in sorted({i for a in ARMS for i in cc[a]}, key=lambda z: -max(cc[a][z] for a in ARMS)):
    b, f = cc["base"][k], cc["flourishing"][k]
    if b == 0 and f == 0:
        continue
    p = stats.fisher_exact([[f, N - f], [b, N - b]])[1]
    print("%-5s %-44s %6d %7d %9.4f %s"
          % (k, LAB.get(k, "?")[:44], b, f, p, "*" if p < 0.05 else ""))

print()
print("ORIGINAL single-rating counts were: item 4 -> base 1, flourishing 15")
f_o = stats.fisher_exact([[15, 181 - 15], [1, 181 - 1]])[1]
print("   original item-4 contrast  : 15 vs 1 of 181   Fisher p=%.5f" % f_o)
b4, f4 = cc["base"][4], cc["flourishing"][4]
f_n = stats.fisher_exact([[f4, N - f4], [b4, N - b4]])[1]
print("   x3 item-4 contrast        : %d vs %d of %d   Fisher p=%.4f" % (f4, b4, N, f_n))
b6, f6 = cc["base"][6], cc["flourishing"][6]
f_6 = stats.fisher_exact([[f6, N - f6], [b6, N - b6]])[1]
print("   x3 item-6 contrast        : %d vs %d of %d   Fisher p=%.4f" % (f6, b6, N, f_6))
print()
print("combined 4+6 (NOT pre-registered -- hypothesis, not a rescue):")
c46 = {a: 0 for a in ARMS}
for p in x3_214:
    for a in ARMS:
        v = agg[bp[p][a]]
        c, ns = Counter(), 0
        for r in v["all"]:
            if r.get("score") is None:
                continue
            ns += 1
            for i in set(r.get("violated") or []):
                c[i] += 1
        items = {i for i, k in c.items() if k * 2 > ns}
        if items & {4, 6}:
            c46[a] += 1
p46 = stats.fisher_exact([[c46["flourishing"], N - c46["flourishing"]],
                          [c46["base"], N - c46["base"]]])[1]
print("   base %d  flourishing %d  sycophancy %d  of %d   Fisher p=%.5f"
      % (c46["base"], c46["flourishing"], c46["sycophancy"], N, p46))

print()
print("=" * 78)
print("STABILITY OF THE ATTRIBUTIONS THEMSELVES")
print("=" * 78)
print("For pairs with 3 scored replicates, how often do all 3 agree on item 4?")
agree4 = Counter()
for p, v in agg.items():
    if not v or v["n"] != 3:
        continue
    hits = sum(1 for r in v["all"]
               if r.get("score") is not None and 4 in set(r.get("violated") or []))
    agree4[hits] += 1
tot = sum(agree4.values())
for k in sorted(agree4):
    print("   item 4 fired in %d of 3 replicates : %4d pairs (%.1f%%)"
          % (k, agree4[k], 100.0 * agree4[k] / tot))
unan = agree4.get(0, 0) + agree4.get(3, 0)
print("   unanimous (0 or 3)                : %4d of %d = %.1f%%"
      % (unan, tot, 100.0 * unan / tot))
print("   -> the share of item-4 calls that a single rating would get wrong")
print("      is the %.1f%% that are split." % (100.0 * (tot - unan) / tot))
