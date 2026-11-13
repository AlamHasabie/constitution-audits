#!/usr/bin/env bash
#
# Serve all three Flourishing-pilot target arms from ONE vLLM server.
#
# Why one server: the arms are google/gemma-3-4b-it plus LoRA adapters trained on
# it, so serving the base and the adapters together means the base arm is
# literally the same weights the adapters sit on. Nothing about the base can
# differ between arms, and it fits on one GPU.
#
# SURF's own `vllm:` provider cannot do this -- surf/core/vllm_server.py builds
# its command with only --model/--port/--tensor-parallel-size/
# --gpu-memory-utilization/--max-model-len, so no --enable-lora and no way to
# name a subfolder. The arms are addressed through SURF's URL provider form
# instead, which needs no code change.
#
# Usage:
#   ./scripts/serve_targets.sh
#   ./scripts/serve_targets.sh --port 8001 --max-model-len 4096
#   ./scripts/serve_targets.sh -- --enforce-eager        # pass through to vllm
#
# Ctrl-C stops the server.

set -euo pipefail

BASE_ID="google/gemma-3-4b-it"
ADAPTER_DIR="adapters"
PORT=8000
# gemma-3-4b-it advertises a 128k context. SURF caps target responses at 2048
# tokens and its prompts are short, so a smaller window here just frees KV cache.
MAX_MODEL_LEN=8192
GPU_UTIL=0.90
TP_SIZE=""
EXTRA_ARGS=()

usage() {
    sed -n '2,25p' "$0" | sed 's/^#\s\?//'
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --base)            BASE_ID="$2"; shift 2 ;;
        --adapter-dir)     ADAPTER_DIR="$2"; shift 2 ;;
        --port)            PORT="$2"; shift 2 ;;
        --max-model-len)   MAX_MODEL_LEN="$2"; shift 2 ;;
        --gpu-util)        GPU_UTIL="$2"; shift 2 ;;
        --tensor-parallel-size) TP_SIZE="$2"; shift 2 ;;
        -h|--help)         usage 0 ;;
        --)                shift; EXTRA_ARGS=("$@"); break ;;
        *)                 echo "unknown option: $1" >&2; usage 2 ;;
    esac
done

cd "$(dirname "$0")/.."   # surf/

if [[ ! -d "$ADAPTER_DIR" ]]; then
    echo "no adapter directory at $ADAPTER_DIR" >&2
    echo "run: uv run scripts/fetch_persona_adapters.py" >&2
    exit 1
fi

# Discover adapters: any subfolder carrying an adapter_config.json.
LORA_MODULES=()
PERSONAS=()
for cfg in "$ADAPTER_DIR"/*/adapter_config.json; do
    [[ -e "$cfg" ]] || continue
    d="$(dirname "$cfg")"
    name="$(basename "$d")"
    PERSONAS+=("$name")
    LORA_MODULES+=("${name}=$(cd "$d" && pwd)")
done

if [[ ${#PERSONAS[@]} -eq 0 ]]; then
    echo "found no adapter_config.json under $ADAPTER_DIR/*/" >&2
    echo "run: uv run scripts/fetch_persona_adapters.py" >&2
    exit 1
fi

# Read the rank off the adapters rather than hardcoding it. vLLM's default
# --max-lora-rank is 16 and these are rank 64, so getting this wrong is a hard
# failure at load time.
MAX_RANK="$(python3 -I -c '
import json, sys, pathlib
ranks = []
for p in sys.argv[1:]:
    ranks.append(json.loads(pathlib.Path(p).read_text(encoding="utf-8")).get("r", 0))
print(max(ranks) if ranks else 64)
' "$ADAPTER_DIR"/*/adapter_config.json)"

if [[ -z "$TP_SIZE" ]]; then
    if command -v nvidia-smi >/dev/null 2>&1; then
        TP_SIZE="$(nvidia-smi --list-gpus | wc -l | tr -d ' ')"
    else
        TP_SIZE=1
    fi
fi
[[ "$TP_SIZE" -ge 1 ]] 2>/dev/null || TP_SIZE=1

if ! uv run --extra vllm which vllm >/dev/null 2>&1; then
    echo "vllm is not installed in this environment" >&2
    echo "run: uv sync --extra vllm" >&2
    exit 1
fi

if [[ ! -f .env ]]; then
    echo "warning: no surf/.env -- the base repo is gated and needs HF_TOKEN" >&2
fi
set -a; [[ -f .env ]] && . ./.env; set +a

LOG="vllm_serve_${PORT}.log"

echo "Serving the Flourishing pilot arms"
echo "  Base:        $BASE_ID"
echo "  Adapters:    ${PERSONAS[*]}"
echo "  LoRA rank:   $MAX_RANK (from adapter_config.json; vLLM default cap is 16)"
echo "  Port:        $PORT"
echo "  Max len:     $MAX_MODEL_LEN"
echo "  GPUs (TP):   $TP_SIZE"
echo "  Log:         $(pwd)/$LOG"
echo

uv run --extra vllm vllm serve "$BASE_ID" \
    --port "$PORT" \
    --enable-lora \
    --max-lora-rank "$MAX_RANK" \
    --max-loras "${#PERSONAS[@]}" \
    --lora-modules "${LORA_MODULES[@]}" \
    --max-model-len "$MAX_MODEL_LEN" \
    --gpu-memory-utilization "$GPU_UTIL" \
    --tensor-parallel-size "$TP_SIZE" \
    "${EXTRA_ARGS[@]}" > "$LOG" 2>&1 &
SERVER_PID=$!

cleanup() {
    echo
    echo "stopping vLLM (pid $SERVER_PID)"
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

printf "waiting for the server"
for _ in $(seq 1 300); do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo
        echo "vLLM exited during startup." >&2
        echo >&2

        # Name the cause rather than making you read a 200-line traceback. These
        # are the four that actually happen with this model and these adapters.
        if grep -qiE "gated repo|is restricted|401 Client Error" "$LOG"; then
            echo "CAUSE: the base repo is gated and this token cannot read it." >&2
            echo >&2
            echo "  1. accept the licence at https://huggingface.co/${BASE_ID}" >&2
            echo "  2. put a read-scope token in surf/.env as HF_TOKEN" >&2
            echo "  3. confirm with: uv run scripts/fetch_persona_adapters.py" >&2
            echo >&2
            echo "     (that script checks base access up front, so it tells you" >&2
            echo "      in seconds instead of after a model load)" >&2
        elif grep -qiE "max_lora_rank|not supported.*lora|lora.*not supported|unsupported lora" "$LOG"; then
            echo "CAUSE: vLLM rejected the LoRA configuration." >&2
            echo >&2
            echo "  Rank passed was --max-lora-rank $MAX_RANK, read from" >&2
            echo "  adapter_config.json. If the complaint is about target modules," >&2
            echo "  check vLLM supports LoRA on each one for this architecture --" >&2
            echo "  these adapters include gate_up_proj and down_proj." >&2
        elif grep -qiE "out of memory|No available memory|KV cache" "$LOG"; then
            echo "CAUSE: not enough GPU memory." >&2
            echo >&2
            echo "  Retry with a smaller window and/or a lower utilisation:" >&2
            echo "    ./scripts/serve_targets.sh --max-model-len 4096 --gpu-util 0.80" >&2
        elif grep -qiE "No CUDA GPUs are available|no such device|Found no NVIDIA driver" "$LOG"; then
            echo "CAUSE: no usable GPU on this machine." >&2
            echo >&2
            echo "  These arms are local weights, so they need one. The judge and" >&2
            echo "  generator are remote APIs and are unaffected." >&2
        else
            echo "Last 40 lines of $LOG:" >&2
            echo >&2
            tail -40 "$LOG" >&2
        fi
        echo >&2
        echo "Full log: $(pwd)/$LOG" >&2
        exit 1
    fi
    if curl -sf "http://localhost:${PORT}/health" >/dev/null 2>&1; then
        echo " ready"
        break
    fi
    printf "."
    sleep 2
done
echo

echo "Served models:"
curl -sf "http://localhost:${PORT}/v1/models" \
    | python3 -I -c 'import json,sys; [print("  "+m["id"]) for m in json.load(sys.stdin)["data"]]' \
    2>/dev/null || echo "  (could not list)"
echo

echo "SURF target strings -- pass these verbatim:"
echo
echo "  base         http://localhost:${PORT}/v1:${BASE_ID}"
for p in "${PERSONAS[@]}"; do
    label="$p"
    [[ "$p" == "goodness" ]] && label="flourishing"
    printf "  %-12s http://localhost:%s/v1:%s\n" "$label" "$PORT" "$p"
done
echo
echo "Check them through SURF's own model layer, in another shell:"
echo "  cd surf && uv run scripts/check_targets.py --port ${PORT}"
echo
echo "Ctrl-C to stop."
wait "$SERVER_PID"
