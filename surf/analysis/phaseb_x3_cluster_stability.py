"""Does the item-level instability wash out when 1/3/4/6 are merged?

argv[1] = original Phase B records (untrusted bundle)
argv[2] = x3 records
"""
import hashlib
import io
import json
import re
import sys
from collections import Counter, defaultdict

_WS = re.compile(r"\s+")
ARMS = ["base", "flourishing", "sycophancy"]
CLUSTER = {1, 3, 4, 6}


def norm(t):
    return _WS.sub(" ", (t or "").strip().lower())


def pid_of(q, r):
    return hashlib.sha256((norm(q) + "\x00" + norm(r)).encode()).hexdigest()[:16]


def load(p):
    return [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]


orig, new = load(sys.argv[1]), load(sys.argv[2])
meta = {pid_of(r["query"], r["response"]):
        {"prompt_id": r["prompt_id"], "arm": r["target_label"],
         "orig_score": r.get("score"), "orig_viol": r.get("violated") or []}
        for r in orig}

reps = defaultdict(list)
for r in new:
    reps[r["pair_id"]].append(r)

bp = defaultdict(dict)
for pid, m in meta.items():
    if any(x.get("score") is not None for x in reps.get(pid, [])):
        bp[m["prompt_id"]][m["arm"]] = pid
complete = sorted(p for p in bp if all(a in bp[p] for a in ARMS))
N = len(complete)
print("complete prompts: %d\n" % N)


def counts(rule):
    out = {a: {"cluster": 0, "any": 0, 4: 0, 6: 0, 1: 0} for a in ARMS}
    for p in complete:
        for a in ARMS:
            rs = [r for r in reps[bp[p][a]] if r.get("score") is not None]
            if rule == "single":
                items = set(meta[bp[p][a]]["orig_viol"] or [])
            elif rule == "majority":
                c = Counter()
                for r in rs:
                    for i in set(r.get("violated") or []):
                        c[i] += 1
                items = {i for i, k in c.items() if k * 2 > len(rs)}
            else:  # union across replicates
                items = {i for r in rs for i in set(r.get("violated") or [])}
            items = {int(i) for i in items if str(i).isdigit()}
            if items & CLUSTER:
                out[a]["cluster"] += 1
            if items:
                out[a]["any"] += 1
            for k in (1, 4, 6):
                if k in items:
                    out[a][k] += 1
    return out


print("%-10s %-13s %8s %8s %8s %10s %8s"
      % ("rule", "arm", "item1", "item4", "item6", "cluster", "any"))
res = {}
for rule in ("single", "majority", "union"):
    c = counts(rule)
    res[rule] = c
    for a in ARMS:
        print("%-10s %-13s %8d %8d %8d %10d %8d"
              % (rule, a, c[a][1], c[a][4], c[a][6], c[a]["cluster"], c[a]["any"]))
    print()

print("SPREAD across the three rules (max-min, as %% of the %d prompts):" % N)
print("%-13s %10s %10s %10s %12s %10s" % ("arm", "item1", "item4", "item6", "cluster", "any"))
for a in ARMS:
    row = []
    for k in (1, 4, 6, "cluster", "any"):
        v = [res[r][a][k] for r in ("single", "majority", "union")]
        row.append(100.0 * (max(v) - min(v)) / N)
    print("%-13s %9.1f%% %9.1f%% %9.1f%% %11.1f%% %9.1f%%" % (a, *row))

print()
print("flourishing-minus-base GAP under each rule:")
print("%-10s %8s %8s %8s %10s %8s" % ("rule", "item1", "item4", "item6", "cluster", "any"))
for rule in ("single", "majority", "union"):
    c = res[rule]
    print("%-10s %8d %8d %8d %10d %8d"
          % (rule, *[c["flourishing"][k] - c["base"][k]
                     for k in (1, 4, 6, "cluster", "any")]))
