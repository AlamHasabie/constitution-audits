"""Is the instability in DETECTION or in LABELLING?

If the judge reliably detects a behaviour but assigns it to item 4 or item 6
interchangeably, then item-4 counts are unstable while item-(4 or 6) counts are
stable. That is a testable distinction.
"""
import hashlib
import io
import json
import re
import sys
from collections import Counter, defaultdict

import numpy as np

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

om = {}
for r in orig:
    om[pid_of(r["query"], r["response"])] = r
reps = defaultdict(list)
for r in new:
    reps[r["pair_id"]].append(r)

bp = defaultdict(dict)
for p, r in om.items():
    bp[r["prompt_id"]][r["target_label"]] = p
both = sorted(p for p in bp
              if all(a in bp[p] for a in ARMS)
              and all(om[bp[p][a]].get("score") is not None for a in ARMS)
              and all(any(x.get("score") is not None for x in reps.get(bp[p][a], []))
                      for a in ARMS))
print("comparison set: %d prompts complete in both passes" % len(both))
print()


def orig_fires(p, a, items):
    return bool(set(om[bp[p][a]].get("violated") or []) & items)


def x3_rate(p, a, items):
    rr = [r for r in reps[bp[p][a]] if r.get("score") is not None]
    if not rr:
        return None
    return sum(1 for r in rr if set(r.get("violated") or []) & items) / len(rr)


print("=" * 76)
print("DETECTION vs LABELLING")
print("=" * 76)
print("For each definition, the ORIGINAL single-pass count and the x3 expected")
print("count per pass (sum of per-pair rates) on the same %d prompts." % len(both))
print()
print("%-22s %-13s %8s %10s %9s" % ("definition", "arm", "original", "x3/pass", "ratio"))
for label, items in [("item 4 only", {4}), ("item 6 only", {6}),
                     ("item 4 OR 6", {4, 6}), ("item 1 only", {1})]:
    for a in ARMS:
        o = sum(1 for p in both if orig_fires(p, a, items))
        x = sum(x3_rate(p, a, items) or 0.0 for p in both)
        print("%-22s %-13s %8d %10.1f %9s"
              % (label, a, o, x, ("%.2fx" % (x / o)) if o else "-"))
    print()

print("=" * 76)
print("CONTRAST STABILITY: flourishing-minus-base, original vs x3")
print("=" * 76)
for label, items in [("item 4 only", {4}), ("item 6 only", {6}),
                     ("item 4 OR 6", {4, 6}), ("item 1 only", {1})]:
    of = sum(1 for p in both if orig_fires(p, "flourishing", items))
    ob = sum(1 for p in both if orig_fires(p, "base", items))
    xf = sum(x3_rate(p, "flourishing", items) or 0.0 for p in both)
    xb = sum(x3_rate(p, "base", items) or 0.0 for p in both)
    print("%-14s original %2d vs %2d (%.1fx)    x3 %4.1f vs %4.1f (%.1fx)"
          % (label, of, ob, of / max(ob, 1e-9), xf, xb, xf / max(xb, 1e-9)))

print()
print("=" * 76)
print("THE MECHANISM: same evidence span, different assertion number?")
print("=" * 76)
print("Pairs where the original named item 4 and some replicate named 6 but not 4.")
print("If the quoted span is the same text, the judge detected one thing and")
print("labelled it two ways.")
print()


def spans(raw, n):
    if not raw:
        return []
    return re.findall(r'<span n="%s">(.*?)</span>' % n, raw, re.S)


shown = 0
for p, r in om.items():
    if 4 not in set(r.get("violated") or []):
        continue
    for x in reps[p]:
        if x.get("score") is None:
            continue
        v = set(x.get("violated") or [])
        if 6 in v and 4 not in v:
            o4 = [s.strip()[:90] for s in spans(r.get("raw_judge_output"), 4)]
            n6 = [s.strip()[:90] for s in spans(x.get("raw_judge_output"), 6)]
            if o4 and n6:
                print("pair %s  arm=%s" % (p[:8], r.get("target_label")))
                print("   orig  span n=4 : %s" % o4[0])
                print("   x3    span n=6 : %s" % n6[0])
                a, b = norm(o4[0]), norm(n6[0])
                ov = len(set(a.split()) & set(b.split())) / max(len(set(a.split()) | set(b.split())), 1)
                print("   word overlap   : %.0f%%" % (100 * ov))
                print()
                shown += 1
            break
    if shown >= 6:
        break
if not shown:
    print("   (no such case found)")

print("=" * 76)
print("ARE 4 AND 6 CO-FIRED? (within a single rating, all passes pooled)")
print("=" * 76)
rows = [r for r in orig if r.get("score") is not None] + \
       [r for r in new if r.get("score") is not None]
c = Counter()
for r in rows:
    v = set(r.get("violated") or [])
    c[(4 in v, 6 in v)] += 1
tot = sum(c.values())
for k in [(True, True), (True, False), (False, True), (False, False)]:
    print("   item4=%-5s item6=%-5s : %5d (%5.2f%%)" % (k[0], k[1], c[k], 100.0 * c[k] / tot))
n4 = c[(True, True)] + c[(True, False)]
n6 = c[(True, True)] + c[(False, True)]
print()
print("   P(item6 | item4) = %.2f     P(item6) = %.2f   -> lift %.1fx"
      % (c[(True, True)] / max(n4, 1), n6 / tot, (c[(True, True)] / max(n4, 1)) / (n6 / tot)))
