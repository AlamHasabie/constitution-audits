# Finding: MiMo-V2.6-Flash is unusable at judge temperature 0.2

Aborted after 175 of 1953 calls. **Do not use these records as scores.**

## Result

| judge temperature | rows | collapse rate |
|---|---:|---:|
| 1.0 (original phase B) | 651 | 7.4% |
| 0.2 (this run) | 175 | **85.1%** |

Lowering the judge temperature made the failure it was meant to fix
**eleven times worse**. The hypothesis behind decision 2026-11-05-B is refuted.

## It is not the token cap

The same run also lowered `max_tokens` 2048 -> 1024, so the two changes are
confounded in principle. They are not in fact:

| | n | min | p50 | p90 | max |
|---|---:|---:|---:|---:|---:|
| scored | 26 | 179 | 464 | 611 | 671 |
| failed | 149 | 0 | 284 | 938 | 3154 |

- Failed outputs are **shorter** than the cap allows. 1024 tokens is roughly
  4000 characters; the longest failure is 3154 and the median is 284.
- **0 of 149** failures contain `<violated>`, `<evidence>` or `<score>`. A
  truncated good answer would begin with `<violated>` and stop later; none does.
  The output is degenerate from the first character.
- 14 of 149 are empty.

So the cap never bound. The temperature is the cause.

## What the failures look like

Mixed-script token salad with a broken-sampler signature -- Polish fragments
(`niektory`, `wzgle`, `wlasciw`) interleaved with CJK and code punctuation,
from the first token onward, with no attempt at the output format.

## Reading of it

MiMo-V2.6-Flash as served by DeepInfra appears to have no usable low-temperature
regime. Near-greedy decoding drives it into repetition/garbage immediately. This
was flagged as a risk in 2026-11-05-B ("greedy decoding can lock into a
repetition loop with no way out") and then dismissed; the risk was the finding.
1.0 is not an arbitrary inherited default for this judge -- it is close to the
only operating point measured to work.

## What this does and does not change

- **Does not vindicate the 7.4% loss at 1.0.** That loss is still
  arm-correlated (10 / 14 / 24 of 217) and still biases per-arm means.
- **Changes the fix.** Retries, not temperature, are the mitigation available
  for this judge. The retry path is unaffected by this finding and was verified
  separately.
- **Leaves open** whether an intermediate temperature (0.6-0.9) is better than
  1.0. Unmeasured. A ~5-point sweep over a small pair sample would settle it
  cheaply, and should be run before any default is changed again.
