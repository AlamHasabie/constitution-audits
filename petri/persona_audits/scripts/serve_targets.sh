#!/usr/bin/env bash
#
# Serve the Petri persona-audit arms from ONE vLLM server:
# google/gemma-3-4b-it plus the goodness and sycophancy LoRA adapters.
#
# Thin wrapper over surf/scripts/serve_targets.sh, which does the real work
# (adapter discovery, --max-lora-rank off the configs, health wait, failure
# diagnosis). Two Petri-specific defaults are the reason it exists:
#
# 1. --max-model-len 32768, not SURF's 8192. That 8192 is correct for SURF --
#    short prompts, responses capped at 2048 tokens -- but a Petri audit runs up
#    to 30 turns against a transcript that grows every turn, so 8192 truncates
#    mid-audit. gemma-3-4b-it advertises 128k; 32k is headroom without giving
#    the whole GPU to KV cache. SURF's default is left alone so the pilot's arms
#    are unchanged.
#
# 2. --override-generation-config, to put the arms on the persona's nominal
#    sampling point. This is decision 2026-11-05-A
#    (methodology/flourishing_decision_log.md) applied to Petri, and Petri needs
#    it more than SURF did. SURF sent temperature explicitly on every call, so
#    only top_p/top_k fell through. Petri sends NONE of the three: both
#    run_flourishing.py and petri's call_target build a GenerateConfig that
#    leaves temperature, top_p and top_k unset, so all three come from the
#    server and the server is the only place they can be set.
#
#    Left alone, the arms would run at vLLM's temperature 1.0 with gemma's own
#    generation_config.json forcing top_k=64 and top_p=0.95 -- hotter and more
#    truncated than the persona cards ask for (temperature 0.7, top_p 0.9, top_k
#    disabled, min_p 0.0). For a character audit the claim is about dispositions,
#    so the nominal point is the defensible one.
#
#    Override it with `--sampling default` to take vLLM's/gemma's behaviour, or
#    pass your own --override-generation-config after `--`.
#
# Usage:
#   ./scripts/serve_targets.sh
#   ./scripts/serve_targets.sh --port 8001
#   ./scripts/serve_targets.sh --sampling default
#   ./scripts/serve_targets.sh -- --enforce-eager      # after -- goes to vllm
#
# Needs HF_TOKEN readable by surf/scripts/serve_targets.sh (it sources
# surf/.env): google/gemma-3-4b-it is gated. See .env.example at the repo root.
#
# Ctrl-C stops the server.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
SURF_SCRIPT="$ROOT/surf/scripts/serve_targets.sh"
ADAPTER_DIR="$ROOT/adapters"

# The persona cards' recommended point. min_p is vLLM's default (0.0) already.
SAMPLING_OVERRIDE='{"temperature":0.7,"top_p":0.9,"top_k":-1}'
MAX_MODEL_LEN=32768

if [[ ! -x "$SURF_SCRIPT" && ! -f "$SURF_SCRIPT" ]]; then
    echo "cannot find the underlying serve script at:" >&2
    echo "  $SURF_SCRIPT" >&2
    exit 1
fi

if [[ ! -d "$ADAPTER_DIR" ]]; then
    echo "no adapter directory at $ADAPTER_DIR" >&2
    echo "fetch them first:" >&2
    echo "  cd $ROOT/surf && .venv/bin/python -I scripts/fetch_persona_adapters.py --out ../adapters" >&2
    exit 1
fi

# Split our own flags from the ones destined for vllm (after `--`).
OWN_ARGS=()
VLLM_ARGS=()
seen_sep=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --) seen_sep=1; shift; continue ;;
        --sampling)
            if [[ $seen_sep -eq 0 ]]; then
                case "${2:-}" in
                    default)  SAMPLING_OVERRIDE="" ;;
                    nominal)  : ;;  # already the default
                    *) echo "--sampling takes 'nominal' or 'default'" >&2; exit 2 ;;
                esac
                shift 2; continue
            fi
            ;;
    esac
    if [[ $seen_sep -eq 0 ]]; then OWN_ARGS+=("$1"); else VLLM_ARGS+=("$1"); fi
    shift
done

# Ours go first so a flag the caller repeats wins: surf's parser assigns on each
# occurrence, so the later one is the one that takes effect.
SURF_OWN=(--adapter-dir "$ADAPTER_DIR" --max-model-len "$MAX_MODEL_LEN")
SURF_VLLM=()
[[ -n "$SAMPLING_OVERRIDE" ]] && SURF_VLLM=(--override-generation-config "$SAMPLING_OVERRIDE")

echo "Petri persona-audit arms"
echo "  Adapters:  $ADAPTER_DIR"
echo "  Max len:   $MAX_MODEL_LEN  (SURF's script defaults to 8192; too small for 30 turns)"
if [[ -n "$SAMPLING_OVERRIDE" ]]; then
    echo "  Sampling:  $SAMPLING_OVERRIDE  (persona nominal; Petri sends none of these itself)"
else
    echo "  Sampling:  server/gemma defaults -- NOT the persona's nominal point"
fi
echo
echo "Petri target strings for --target:"
echo "  base         vllm/google/gemma-3-4b-it"
echo "  goodness     vllm/google/gemma-3-4b-it:goodness"
echo "  sycophancy   vllm/google/gemma-3-4b-it:sycophancy"
echo
echo "(The arm names printed below by the SURF script are SURF's URL form -- use"
echo " the vllm/ strings above for Petri, with VLLM_BASE_URL set in .env.)"
echo

exec bash "$SURF_SCRIPT" \
    "${SURF_OWN[@]}" \
    ${OWN_ARGS[@]+"${OWN_ARGS[@]}"} \
    -- \
    ${SURF_VLLM[@]+"${SURF_VLLM[@]}"} \
    ${VLLM_ARGS[@]+"${VLLM_ARGS[@]}"}
