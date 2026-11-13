# STOPPED — incomplete, do not read as a sweep

Stopped by request partway through the first of five temperature cells.
Collected: temperature 0.2 only, 25 of 60 pairs, every one a no-score
failure (25/25). Temperatures 0.4, 0.6, 0.8 and 1.0 were never started.

DESIGN.md describes the intended run, not this one. Nothing here supports
a comparison across temperatures, and the 0.2 records are not scores.

The one thing it adds to decision 2026-11-05-B: on a paired sample, 0.2
failed on 25 of 25, against 85.1% on the earlier unpaired sample. That is
consistent and slightly worse, so the reversal in 1fddd48 stands.

To resume, rerun the command in DESIGN.md: run_rater resumes on
(pair_id, rater_label, replicate), so the 25 already collected are not
repaid.
