#!/usr/bin/env bash
# quick_render.sh — quick still renders of every stationary camera in a
# .blend, using the ddgeoviztools Docker image (no local Blender required).
#
# Builds the Docker image on first use (and any time src/, Dockerfile, or
# requirements.txt change), then invokes Blender in the container to render
# Cam_Transverse, Cam_Side, and Cam_Perspective from the supplied .blend.
# Cam_Hero is skipped — it's the animated cinematic camera.
#
# Usage:
#   scripts/quick_render.sh scene.blend [options]
#
# Options:
#   -o, --out DIR        Output directory for PNGs (default: <blend-dir>/renders/).
#       --samples N      Cycles samples (default: 32).
#       --width  W       Render width  in pixels (default: 1280).
#       --height H       Render height in pixels (default: 720).
#       --device CPU|GPU Cycles device (default: CPU; GPU needs the NVIDIA
#                        Container Toolkit and adds --gpus all).
#       --no-compositor  Bypass the scene's compositor (raw Cycles output).
#                        Useful for diagnosing whether the post chain is
#                        blowing out the image vs. the underlying scene.
#       --image NAME     Override Docker image tag (default: ddgeoviztools).
#       --no-build       Skip the build / staleness check; just run.
#   -h, --help           Show this help and exit.
#
# Examples:
#   scripts/quick_render.sh /tmp/scene.blend
#   scripts/quick_render.sh scene.blend --samples 64 --width 1920 --height 1080
#   scripts/quick_render.sh scene.blend --no-compositor -o /tmp/raw_check

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RENDER_PY_HOST="$SCRIPT_DIR/render_cameras.py"

usage() {
    sed -n '2,/^set -e/p' "$0" | sed -n '/^#/p' | sed 's/^# \{0,1\}//' | sed '$d'
    exit "${1:-0}"
}

# --- Defaults ---
OUT=""
SAMPLES=32
WIDTH=1280
HEIGHT=720
DEVICE="CPU"
NO_COMP=0
IMAGE="ddgeoviztools"
DO_BUILD=1
BLEND=""

# --- Parse args ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)        usage 0 ;;
        -o|--out)         OUT="$2"; shift 2 ;;
        --samples)        SAMPLES="$2"; shift 2 ;;
        --width)          WIDTH="$2"; shift 2 ;;
        --height)         HEIGHT="$2"; shift 2 ;;
        --device)         DEVICE="$2"; shift 2 ;;
        --no-compositor)  NO_COMP=1; shift ;;
        --image)          IMAGE="$2"; shift 2 ;;
        --no-build)       DO_BUILD=0; shift ;;
        --)               shift; break ;;
        -*)               echo "unknown option: $1" >&2; usage 2 ;;
        *)
            if [[ -z "$BLEND" ]]; then
                BLEND="$1"
            else
                echo "unexpected extra argument: $1" >&2
                usage 2
            fi
            shift
            ;;
    esac
done

if [[ -z "$BLEND" ]]; then
    echo "error: missing .blend path" >&2
    usage 2
fi
if [[ ! -f "$BLEND" ]]; then
    echo "error: not a file: $BLEND" >&2
    exit 1
fi
if [[ ! -f "$RENDER_PY_HOST" ]]; then
    echo "error: render_cameras.py not found next to this script: $RENDER_PY_HOST" >&2
    exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
    echo "error: docker not found on PATH.  Install Docker to use quick_render.sh." >&2
    exit 1
fi

# --- Absolutize host paths (Docker can't bind relative paths) ---
BLEND_HOST_DIR="$(cd "$(dirname "$BLEND")" && pwd)"
BLEND_NAME="$(basename "$BLEND")"
BLEND_HOST="$BLEND_HOST_DIR/$BLEND_NAME"

if [[ -z "$OUT" ]]; then
    OUT="$BLEND_HOST_DIR/renders"
fi
mkdir -p "$OUT"
OUT_HOST="$(cd "$OUT" && pwd)"

# --- Build (or rebuild) the Docker image if src/Dockerfile/requirements
#     changed since the last build.  Mirrors the hashing pattern in run.sh
#     so a single source change triggers exactly one rebuild across both
#     wrappers.
build_if_stale() {
    local src_hash img_hash
    src_hash=$(
        find "$REPO_ROOT/src" \
             "$REPO_ROOT/Dockerfile" \
             "$REPO_ROOT/requirements.txt" \
             -type f 2>/dev/null | sort | xargs md5sum 2>/dev/null \
            | md5sum | cut -d' ' -f1
    )
    img_hash=$(docker image inspect "$IMAGE" \
                   --format '{{index .Config.Labels "build.src_hash"}}' \
                   2>/dev/null || true)

    if [[ "$src_hash" != "$img_hash" ]]; then
        if [[ -z "$img_hash" ]]; then
            echo "==> Building Docker image '$IMAGE' (first run, ~5-10 min) ..."
        else
            echo "==> Building Docker image '$IMAGE' (source changed) ..."
        fi
        docker build -t "$IMAGE" \
            --label "build.src_hash=$src_hash" \
            "$REPO_ROOT"
    fi
}
if [[ "$DO_BUILD" == 1 ]]; then
    build_if_stale
fi

# --- Compose docker run flags ---
GPU_FLAGS=()
if [[ "$DEVICE" == "GPU" ]]; then
    GPU_FLAGS=(--gpus all)
fi

NO_COMP_FLAG=()
if [[ "$NO_COMP" == 1 ]]; then
    NO_COMP_FLAG=(--no-compositor)
fi

# --- Mounts ---
#   /blend (ro)   the directory containing the .blend
#   /scripts (ro) repo scripts dir so render_cameras.py is reachable
#   /out          writable output dir for PNGs
MOUNTS=(
    -v "$BLEND_HOST_DIR:/blend:ro"
    -v "$SCRIPT_DIR:/scripts:ro"
    -v "$OUT_HOST:/out"
)

echo "==> Rendering stationary cameras in $BLEND_HOST"
echo "    image      : $IMAGE"
echo "    out dir    : $OUT_HOST"
echo "    samples    : $SAMPLES"
echo "    resolution : ${WIDTH}x${HEIGHT}"
echo "    device     : $DEVICE"
[[ "$NO_COMP" == 1 ]] && echo "    compositor : DISABLED (--no-compositor)"

exec docker run --rm \
    --entrypoint blender \
    ${GPU_FLAGS[@]+"${GPU_FLAGS[@]}"} \
    "${MOUNTS[@]}" \
    "$IMAGE" \
    --background "/blend/$BLEND_NAME" \
    --python-exit-code 1 \
    --python /scripts/render_cameras.py -- \
    --out /out \
    --samples "$SAMPLES" \
    --width "$WIDTH" --height "$HEIGHT" \
    --device "$DEVICE" \
    ${NO_COMP_FLAG[@]+"${NO_COMP_FLAG[@]}"}
