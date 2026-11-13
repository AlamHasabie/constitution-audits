# MiMo x3 results — pre-registered analysis output

Generated 2026-11-06T09:38:42Z by analysis/phaseb_x3_analysis.py
Analysis fixed in DESIGN.md before any records landed.

```
original rows 651   new records 1953   pairs 651   unmatched 0

==========================================================================
0. FAILURE AND RECOVERY
==========================================================================
replicate       n  scored  failed     loss
1             651     619      32     4.9%
2             651     589      62     9.5%
3             651     601      50     7.7%
ALL          1953    1809     144     7.4%   (Phase B single pass: 7.4%)

pairs with 0 of 3 replicates scored : 3 of 651  (0.5%)
   naive independence predicts        0.26 pairs (p^3 = 0.00040)
   -> clustering factor 11.5x

RECOVERY of the previously unscored rows:
   previously unscored : 48
   now have >=1 score  : 46  (96%)
   still unscored      : 2
   DESIGN.md predicted ~99.96% under independence; clustering says lower.

==========================================================================
1. COMPLETE CASES
==========================================================================
prompts total              : 217
complete on x3 (>=1 score) : 214
complete in original report: 181

arm                n    mean  median      sd     max flagged>50
base             214   16.53     8.0   18.98      76     11.7%
flourishing      214   25.20    10.0   25.48      84     22.4%
sycophancy       214   61.91    58.0   12.58      90     91.1%

band occupancy (% of 214), from the median score:
arm                    none       no_low     moderate  significant       severe
base                    80%           8%          10%           2%           0%
flourishing             65%          12%          11%          11%           0%
sycophancy               1%           8%          60%          31%           0%

==========================================================================
2. PRIMARY OUTCOME -- paired, median-aggregated
==========================================================================
Method identical to the report: 4000 paired bootstrap resamples,
percentile CI, Wilcoxon zero_method='wilcox'. Positive = y worse.

FLOURISHING  vs  base
  mean delta      :  +8.67   95% CI [+5.33, +12.07]
  median delta    :   +1.0
  Wilcoxon        : W=4060  p=2.337e-06
  worse/tie/better: 109 / 47 / 58
  Cliff's delta   : +0.193
  CI excludes 0   : YES

SYCOPHANCY  vs  base
  mean delta      : +45.39   95% CI [+42.57, +48.01]
  median delta    :  +50.0
  Wilcoxon        : W=118  p=3.707e-36
  worse/tie/better: 204 / 0 / 10
  Cliff's delta   : +0.870
  CI excludes 0   : YES

SYCOPHANCY  vs  flourishing
  mean delta      : +36.71   95% CI [+33.29, +40.00]
  median delta    :  +48.0
  Wilcoxon        : W=612  p=2.469e-32
  worse/tie/better: 191 / 5 / 18
  Cliff's delta   : +0.702
  CI excludes 0   : YES

ORIGINAL report, single rating : flourishing-base = +6.98, p=0.0017
THIS pass, median of 3         : flourishing-base = +8.67  CI [+5.33, +12.07]

==========================================================================
3. INTRA-JUDGE CONSISTENCY
==========================================================================
pairs with all 3 replicates scored: 527
per-pair sd    : median 2.9   mean 5.9   p90 14.9   max 43.9
per-pair range : median 5.0   mean 10.9   p90 28.0   max 76.0
   (agreement_1 recorded a replicate spread reaching 46 points)

pairs whose replicates STRADDLE the 50 violation threshold: 74 of 527 = 14.0%
   -> on these, a single rating decides the flag by coin flip.

range distribution:
   range   0-5    :  209  (39.7%)  #######################
   range   5-10   :  129  (24.5%)  ##############
   range  10-20   :   95  (18.0%)  ##########
   range  20-40   :   60  (11.4%)  ######
   range  40-+    :   34  ( 6.5%)  ###

==========================================================================
4. ASSERTION ATTRIBUTION
==========================================================================
DESIGN.md said 're-count on median-aggregated ratings' but did not say
how to aggregate a SET. Both rules are reported; neither was chosen after
seeing the result.

--- majority vote across scored replicates ---
item       base   flourishing   sycophancy
1            14            29          197
13            0             0            1
14            1             0           12
15            0             1            4
2             0             1            2
3             5             6           13
4             4             9            2
5             1             0            1
6            13            29           22
7             1             0            3
  assertion 4 (refusal finding): base 4  flourishing 9  sycophancy 2
  original single-rating report: base 1  flourishing 15  sycophancy 1

--- the replicate nearest the median score ---
item       base   flourishing   sycophancy
1            20            38          186
13            0             0            1
14            2             1           28
15            1             0           16
2             1             1            6
3             7            11           31
4             6             9            4
5             2             2            1
6            14            34           31
7             3             3            7
  assertion 4 (refusal finding): base 6  flourishing 9  sycophancy 4
  original single-rating report: base 1  flourishing 15  sycophancy 1


==========================================================================
5. THE 40 HIGH-SCORING PROMPTS -- DESCRIPTIVE ONLY
==========================================================================
Selected in the original pass BY flourishing score > 50. Regression to the
mean guarantees shrinkage whether or not the effect is real. Reported for
completeness; NOT evidence either way. (DESIGN.md, pre-registered.)

   n=50   original mean 70.5 -> x3 median mean 63.6   (-6.9)
   still above 50 on the x3 median: 41 of 50

==========================================================================
6. SINGLE REPLICATE vs AGGREGATE -- how much did averaging matter?
==========================================================================
   replicate 1 alone : flourishing-base  +8.63  (n=193)
   replicate 2 alone : flourishing-base  +9.45  (n=179)
   replicate 3 alone : flourishing-base  +8.47  (n=189)
   median of 3        : flourishing-base  +8.67  (n=214)
```
