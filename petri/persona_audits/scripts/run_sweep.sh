#!/usr/bin/env bash
#
# Run the Flourishing persona audit across all three arms for N passes.
#
# run_flourishing.py is one target, one pass per invocation, by design. This is
# the loop around it: it adds nothing to the measurement, only the arm/pass
# bookkeeping that a cross-persona control needs.
#
# Produced results/flourishing/sweep_20261115T132039Z (see its README.md).
#
# Usage:
#   ./scripts/run_sweep.sh                       # passes 1-3 into a new sweep
#   ./scripts/run_sweep.sh --passes 10           # passes 1-10
#   ./scripts/run_sweep.sh --from 8 --passes 10 --sweep sweep_20261115T132039Z
#   ./scripts/run_sweep.sh --arms goodness sycophancy
#
# Run it from petri/. Needs scripts/serve_targets.sh already up, and the
# auditor/judge key in .env at the repo root.
#
# Two properties worth knowing before changing anything here:
#
# 1. **Arms run CONCURRENTLY within a pass, passes sequentially.** Nothing in
#    petri or this script controls for provider-side change between
#    invocations, so the arms being contrasted must be as close together in
#    time as possible. Three sequential arms would put ~25 minutes between the
#    first and last arm of the same pass. It is also free: one sample per run,
#    so petri makes no concurrent calls inside a single invocation.
#
# 2. **It skips a pass whose transcript already exists.** petri writes
#    transcript_<sample id>.json in truncating mode and the dataset is one
#    sample, so every pass writes the same filename. Re-running into an
#    occupied directory would silently destroy the earlier pass rather than
#    fail, which is also why --run-id is set per pass rather than left to the
#    default timestamp.

set -uo pipefail

cd "$(dirname "$0")/.."   # persona_audits/

PY=${PY:-../../.venv/bin/python}
AUDITOR=${AUDITOR:-openai-api/deepinfra/XiaomiMiMo/MiMo-V2.6-Flash}
JUDGE=${JUDGE:-openai-api/deepinfra/meta-llama/Llama-3.3-70B-Instruct-Turbo}
TURNS=${TURNS:-30}
TOOL_FREE=${TOOL_FREE:---tool-free}

ARMS=(base goodness sycophancy)
FROM=1
PASSES=3
SWEEP=""
RESULTS_ROOT="./results/flourishing"

usage() { sed -n '2,30p' "$0" | sed 's/^#\s\?//'; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --passes) PASSES="$2"; shift 2 ;;
        --from)   FROM="$2"; shift 2 ;;
        --sweep)  SWEEP="$2"; shift 2 ;;
        --turns)  TURNS="$2"; shift 2 ;;
        --arms)   ARMS=(); shift
                  while [[ $# -gt 0 && "$1" != --* ]]; do ARMS+=("$1"); shift; done ;;
        --with-tools) TOOL_FREE=""; shift ;;
        -h|--help) usage 0 ;;
        *) echo "unknown option: $1" >&2; usage 2 ;;
    esac
done

[[ -n "$SWEEP" ]] || SWEEP="sweep_$(date -u +%Y%m%dT%H%M%SZ)"
BASE="$RESULTS_ROOT/$SWEEP"
LOGDIR="$BASE/_sweeplogs"
mkdir -p "$LOGDIR"

# A pidfile, not a pgrep pattern: `pgrep -f run_sweep.sh` matches the command
# line of any watcher that greps for it, including itself, so a waiter written
# that way never exits.
echo $$ > "$LOGDIR/sweep.pid"
trap 'rm -f "$LOGDIR/sweep.pid"' EXIT

{
  echo "sweep:     $SWEEP"
  echo "arms:      ${ARMS[*]}"
  echo "passes:    $FROM..$PASSES  (arms concurrent within a pass)"
  echo "auditor:   $AUDITOR"
  echo "judge:     $JUDGE"
  echo "turns:     $TURNS   tool-free: ${TOOL_FREE:-no}"
  echo "started:   $(date -u +%FT%TZ)"
} | tee -a "$LOGDIR/manifest.txt"
echo

target_for() {
    case "$1" in
        base) echo "vllm/google/gemma-3-4b-it" ;;
        *)    echo "vllm/google/gemma-3-4b-it:$1" ;;
    esac
}

FAILED=0
for pass in $(seq "$FROM" "$PASSES"); do
    echo "=== pass $pass/$PASSES  $(date -u +%T)Z ==="
    pids=(); names=()
    for arm in "${ARMS[@]}"; do
        if [[ -f "$BASE/$arm/pass${pass}/all/transcript_F1-15.json" ]]; then
            echo "  SKIP $arm pass$pass (transcript exists)"; continue
        fi
        $PY run_flourishing.py \
            --target "$(target_for "$arm")" \
            --label "$arm" --run-id "pass${pass}" \
            --output-base "$BASE" --max-turns "$TURNS" \
            ${TOOL_FREE:+$TOOL_FREE} \
            --auditor "$AUDITOR" --judge "$JUDGE" \
            > "$LOGDIR/${arm}_pass${pass}.log" 2>&1 &
        pids+=($!); names+=("$arm")
        echo "  launched $arm (pid ${pids[-1]})"
    done
    for i in "${!pids[@]}"; do
        if wait "${pids[$i]}"; then echo "  OK     ${names[$i]} pass$pass"
        else echo "  FAILED ${names[$i]} pass$pass"; FAILED=$((FAILED+1)); fi
    done
    echo
done

echo "finished: $(date -u +%FT%TZ)   failures: $FAILED"
echo "score the sweep with:  $PY scripts/score_sweep.py $BASE"
