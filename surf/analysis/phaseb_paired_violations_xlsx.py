"""The paired violations as a spreadsheet, with the full text in the cells.

Markdown tables cannot hold a multi-line 5,000-character response -- a newline ends
the row -- so the long-form view lives here instead, one prompt per row with every
field in its own cell.

    uv run analysis/phaseb_paired_violations_xlsx.py
"""
import hashlib
import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

REPO = Path(__file__).resolve().parents[1]
ORIG = REPO / "flourishing_pilot_20261105/flourishing_pilot_20261105/surf/results/phaseB/records.jsonl"
NEW = REPO / "results/phaseB_mimo_x3/records.jsonl"
VAL = REPO / "results/phaseB_validation/records.jsonl"
OUT = REPO / "results/phaseB_validation/paired_violations.xlsx"

ARMS = ("base", "flourishing")
BINARY = ("CONFIRMED", "FALSE_POSITIVE")
CELL_LIMIT = 32000  # Excel's hard limit is 32,767
_WS = re.compile(r"\s+")


def norm(t):
    return _WS.sub(" ", (t or "").strip().lower())


def pair_id_of(q, r):
    return hashlib.sha256((norm(q) + "\x00" + norm(r)).encode()).hexdigest()[:16]


def load(p):
    if not p.exists():
        sys.exit(f"missing {p}")
    with io.open(p, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def majority(vs):
    v = [x for x in vs if x in BINARY]
    if not v:
        return "UNRESOLVED"
    c, f = v.count("CONFIRMED"), v.count("FALSE_POSITIVE")
    return "UNRESOLVED" if c == f else ("CONFIRMED" if c > f else "FALSE_POSITIVE")


truncated = []


def fit(text, where):
    t = (text or "").strip()
    if len(t) > CELL_LIMIT:
        truncated.append((where, len(t)))
        return t[:CELL_LIMIT] + "\n\n[TRUNCATED AT 32,000 CHARS -- full text in records.jsonl]"
    return t


def main():
    meta = {}
    for r in load(ORIG):
        meta[pair_id_of(r["query"], r["response"])] = (r["target_label"], r["prompt_id"])

    reps = defaultdict(list)
    for r in load(NEW):
        reps[r["pair_id"]].append(r)

    cell = {}
    for pid, rs in reps.items():
        if pid not in meta:
            continue
        arm, prompt = meta[pid]
        scored = [r for r in rs if isinstance(r.get("score"), (int, float))]
        if not scored:
            continue
        top = max(scored, key=lambda r: r["score"])
        cell[(arm, prompt)] = {
            "pair_id": pid, "query": top["query"], "response": top["response"],
            "score": top["score"], "band": top.get("band"),
            "reasoning": top.get("reasoning") or "",
            "violated": top.get("violated") or [],
            "all_scores": sorted(r["score"] for r in scored),
            "candidate": top["score"] > 50,
        }

    val = load(VAL)
    raters = sorted({r["rater_label"] for r in val})
    best = {}
    for r in val:
        key = (r["case_id"], r["rater_label"])
        prev = best.get(key)
        if prev is None or (r["round"], r["timestamp"]) >= (prev["round"], prev["timestamp"]):
            best[key] = r
    case_of_pair = {r["pair_id"]: r["case_id"] for r in val}

    def verdicts(arm, prompt):
        c = cell.get((arm, prompt))
        if c is None:
            return None, {}
        cid = case_of_pair.get(c["pair_id"])
        if cid is None:
            return ("not flagged" if not c["candidate"] else "not validated"), {}
        per = {l: best[(cid, l)] for l in raters if (cid, l) in best}
        return majority([v["verdict"] for v in per.values()]), per

    def render(per):
        if not per:
            return "Never a validation candidate -- MiMo's max replicate was at or below 50, so no rater saw this arm. This is not an exoneration."
        out = []
        for lbl in raters:
            v = per.get(lbl)
            if not v:
                continue
            out.append(f"[{lbl}] {v['verdict']} (round {v['round']}, confidence {v['confidence']}, "
                       f"assertions {v['assertions'] or 'none'})")
            if v.get("rationale"):
                out.append(f"    rationale: {_WS.sub(' ', v['rationale'])}")
            if v.get("judge_error"):
                out.append(f"    judge error: {_WS.sub(' ', v['judge_error'])}")
            out.append("")
        return "\n".join(out).strip()

    cat_label = {
        "flourishing_only": "A - flourishing violates, base does not",
        "both": "B - both violate",
        "base_only": "C - base violates, flourishing does not",
    }
    order = {"flourishing_only": 0, "both": 1, "base_only": 2}

    rows = []
    for p in sorted({pr for (_, pr) in cell}):
        vb, pb = verdicts("base", p)
        vf, pf = verdicts("flourishing", p)
        if vb is None or vf is None or "CONFIRMED" not in (vb, vf):
            continue
        cat = ("both" if vb == vf == "CONFIRMED"
               else "flourishing_only" if vf == "CONFIRMED" else "base_only")
        rows.append({"prompt": p, "cat": cat, "vb": vb, "vf": vf, "pb": pb, "pf": pf})
    rows.sort(key=lambda r: (order[r["cat"]], r["prompt"]))

    wb = Workbook()
    ws = wb.active
    ws.title = "Violations"

    headers = [
        ("#", 5), ("Prompt ID", 18), ("Cell", 38), ("Query", 70),
        ("Base verdict", 16), ("Flourishing verdict", 18),
        ("Base MiMo max", 13), ("Flour MiMo max", 13),
        ("Base response", 90), ("Flourishing response", 90),
        ("Base judge reasoning", 60), ("Flourishing judge reasoning", 60),
        ("Base validator reasoning", 70), ("Flourishing validator reasoning", 70),
    ]
    head_font = Font(name="Arial", bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="44546A")
    body_font = Font(name="Arial", size=10)
    wrap = Alignment(wrap_text=True, vertical="top")

    for i, (h, w) in enumerate(headers, 1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = head_font
        c.fill = head_fill
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "E2"

    fills = {"flourishing_only": PatternFill("solid", fgColor="FCE4E4"),
             "both": PatternFill("solid", fgColor="FFF2CC"),
             "base_only": PatternFill("solid", fgColor="E2EFDA")}

    for i, r in enumerate(rows, 1):
        p = r["prompt"]
        cb, cf = cell[("base", p)], cell[("flourishing", p)]
        values = [
            i, p, cat_label[r["cat"]], fit(cb["query"], f"{p}/query"),
            r["vb"], r["vf"], cb["score"], cf["score"],
            fit(cb["response"], f"{p}/base_response"),
            fit(cf["response"], f"{p}/flour_response"),
            fit(f"score {cb['score']:.0f}, replicates {cb['all_scores']}, cited "
                f"{cb['violated'] or 'none'}\n\n{cb['reasoning']}", f"{p}/base_reasoning"),
            fit(f"score {cf['score']:.0f}, replicates {cf['all_scores']}, cited "
                f"{cf['violated'] or 'none'}\n\n{cf['reasoning']}", f"{p}/flour_reasoning"),
            fit(render(r["pb"]), f"{p}/base_validators"),
            fit(render(r["pf"]), f"{p}/flour_validators"),
        ]
        for j, v in enumerate(values, 1):
            c = ws.cell(row=i + 1, column=j, value=v)
            c.font = body_font
            c.alignment = wrap
            c.fill = fills[r["cat"]]
        ws.row_dimensions[i + 1].height = 120

    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"

    # ---- the caveat travels with the file -------------------------------
    n = wb.create_sheet("Read me first")
    n.column_dimensions["A"].width = 110
    notes = [
        ("These are panel labels, not established violations.", True),
        ("", False),
        ("On 18 hand-checked cases the three-model panel agreed with a human reader 9 times "
         "-- chance, Cohen kappa 0.00. See validation_reports/surf_flourishing_phaseB_validation.md "
         "section 5. Read this sheet as a record of what three models decided, and as material "
         "for deciding whether they decided well.", False),
        ("", False),
        ("Verdict values", True),
        ("CONFIRMED / FALSE_POSITIVE -- the panel's majority after two rounds.", False),
        ("UNRESOLVED -- the panel tied, or no rater returned a parseable verdict.", False),
        ("not flagged -- MiMo never scored this arm above 50 on any of three replicates, so it "
         "was never a validation candidate and no rater ever saw it. THIS IS NOT AN EXONERATION.", False),
        ("", False),
        ("Before reading the cells as a comparison", True),
        ("Of the 31 'flourishing only' rows, 23 have base 'not flagged' -- the panel never saw "
         "the base arm. Only 8 are cases where the panel adjudicated both arms and split. For the "
         "4 'base only' rows it is 1 of 4. Restricted to prompts the panel saw in both arms, the "
         "contrast is 8 versus 1, exact p = 0.039, rather than 31 versus 4 at p = 3.5e-06.", False),
        ("", False),
        ("Generated by surf/analysis/phaseb_paired_violations_xlsx.py", False),
    ]
    for i, (text, bold) in enumerate(notes, 1):
        c = n.cell(row=i, column=1, value=text)
        c.font = Font(name="Arial", size=11, bold=bold)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        if len(text) > 100:
            n.row_dimensions[i].height = 60

    # ---- every flagged candidate, confirmed or not ----------------------
    # The sheet above only holds prompts with a CONFIRMED arm. This one is the
    # complete flagged set: one row per (arm, prompt) cell MiMo put above 50,
    # with whatever the panel then decided -- including the ones it cleared.
    allc = wb.create_sheet("All flagged candidates")
    ah = [("#", 5), ("Case ID", 14), ("Prompt ID", 18), ("Arm", 13), ("Stratum", 10),
          ("MiMo max", 10), ("Replicates", 14), ("Straddles 50", 12),
          ("PANEL VERDICT", 17)] + [(f"{l} verdict", 16) for l in raters] + [
          ("Query", 70), ("Response", 90), ("Judge reasoning", 60),
          ("Validator reasoning", 70)]
    for i, (h, w) in enumerate(ah, 1):
        c = allc.cell(row=1, column=i, value=h)
        c.font = head_font
        c.fill = head_fill
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        allc.column_dimensions[get_column_letter(i)].width = w
    allc.row_dimensions[1].height = 30
    allc.freeze_panes = "F2"

    vfill = {"CONFIRMED": PatternFill("solid", fgColor="FCE4E4"),
             "FALSE_POSITIVE": PatternFill("solid", fgColor="E2EFDA"),
             "UNRESOLVED": PatternFill("solid", fgColor="D9D9D9")}

    seen, cand_rows = set(), []
    for r in val:
        if r["case_id"] in seen:
            continue
        seen.add(r["case_id"])
        cand_rows.append(r)
    cand_rows.sort(key=lambda r: (r["stratum"] != "candidate", r["arm"], -r["max_score"]))

    for i, rec in enumerate(cand_rows, 1):
        cid, pid = rec["case_id"], rec["pair_id"]
        per = {l: best[(cid, l)] for l in raters if (cid, l) in best}
        mv = majority([v["verdict"] for v in per.values()])
        src = cell.get((rec["arm"], rec["prompt_id"]), {})
        vals = [i, cid, rec["prompt_id"], rec["arm"], rec["stratum"],
                rec["max_score"], str(src.get("all_scores", "")),
                "yes" if rec["straddles_50"] else "no", mv] + \
               [per[l]["verdict"] if l in per else "" for l in raters] + \
               [fit(src.get("query", ""), f"{cid}/q"),
                fit(src.get("response", ""), f"{cid}/r"),
                fit(f"score {rec['judge_score']:.0f}, cited {rec['judge_violated'] or 'none'}"
                    f"\n\n{src.get('reasoning', '')}", f"{cid}/jr"),
                fit(render(per), f"{cid}/vr")]
        for j, v in enumerate(vals, 1):
            c = allc.cell(row=i + 1, column=j, value=v)
            c.font = body_font
            c.alignment = wrap
            c.fill = vfill.get(mv, vfill["UNRESOLVED"])
        allc.row_dimensions[i + 1].height = 110
    allc.auto_filter.ref = f"A1:{get_column_letter(len(ah))}{len(cand_rows) + 1}"

    counts = {k: sum(1 for r in rows if r["cat"] == k) for k in order}
    s = wb.create_sheet("Counts")
    s.column_dimensions["A"].width = 44
    s.column_dimensions["B"].width = 12
    s.cell(row=1, column=1, value="Cell").font = Font(name="Arial", bold=True)
    s.cell(row=1, column=2, value="Prompts").font = Font(name="Arial", bold=True)
    for i, k in enumerate(order, 2):
        s.cell(row=i, column=1, value=cat_label[k]).font = Font(name="Arial")
        s.cell(row=i, column=2, value=counts[k]).font = Font(name="Arial")
    s.cell(row=5, column=1, value="Total prompts with a confirmed arm").font = Font(name="Arial", bold=True)
    s.cell(row=5, column=2, value=len(rows)).font = Font(name="Arial", bold=True)

    wb.save(OUT)

    print(f"{len(rows)} prompt rows + {len(cand_rows)} candidate rows -> {OUT}"
          f"  ({OUT.stat().st_size/1024:.0f} KB)")
    for k in order:
        print(f"  {cat_label[k]:<42}{counts[k]:>4}")
    tally = defaultdict(lambda: defaultdict(int))
    for rec in cand_rows:
        per = {l: best[(rec["case_id"], l)] for l in raters if (rec["case_id"], l) in best}
        tally[(rec["stratum"], rec["arm"])][majority([v["verdict"] for v in per.values()])] += 1
    print("\n  All flagged candidates sheet:")
    print(f"  {'stratum':<11}{'arm':<13}{'CONFIRMED':>10}{'FALSE_POS':>11}{'UNRES':>7}{'total':>7}")
    for k in sorted(tally):
        t = tally[k]
        n_ = sum(t.values())
        print(f"  {k[0]:<11}{k[1]:<13}{t['CONFIRMED']:>10}{t['FALSE_POSITIVE']:>11}"
              f"{t['UNRESOLVED']:>7}{n_:>7}")
    if truncated:
        print(f"\n!! {len(truncated)} cells hit the 32,000-char limit:")
        for where, n_ in truncated:
            print(f"   {where}  ({n_} chars)")
    else:
        print("\nno cell hit the 32,000-char Excel limit -- all text is complete")


if __name__ == "__main__":
    main()
