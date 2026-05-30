#!/usr/bin/env bash
# quick_render.sh — quick still renders of every stationary camera in a .blend.
#
# Hands a .blend file to Blender in background mode and uses
# scripts/render_cameras.py to render Cam_Transverse, Cam_Side, and
# Cam_Perspective (skipping the animated Cam_Hero) at modest size and
# sample count.  Built for fast terminal-only iteration / diagnosis.
#
# Usage:
#   scripts/quick_render.sh scene.blend [options]
#
# Options:
#   -o, --out DIR        Output directory for PNGs (default: alongside .blend
#                        in <blend-dir>/renders/).
#       --samples N      Cycles samples (default: 32).
#       --width  W       Render width  in pixels (default: 1280).
#       --height H       Render height in pixels (default: 720).
#       --device CPU|GPU Cycles device (default: CPU).
#       --no-compositor  Bypass the scene's compositor (raw Cycles output).
#                        Useful when diagnosing whether bloom / glare in
#                        the post chain is blowing out the image.
#       --blender PATH   Override blender binary (default: from PATH).
#   -h, --help           Show this help and exit.
#
# Examples:
#   scripts/quick_render.sh /tmp/scene.blend
#   scripts/quick_render.sh scene.blend --samples 64 --width 1920 --height 1080
#   scripts/quick_render.sh scene.blend --no-compositor -o /tmp/raw_check

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RENDER_PY="$SCRIPT_DIR/render_cameras.py"

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
BLENDER_BIN=""
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
        --blender)        BLENDER_BIN="$2"; shift 2 ;;
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
if [[ ! -f "$RENDER_PY" ]]; then
    echo "error: render_cameras.py not found next to this script: $RENDER_PY" >&2
    exit 1
fi

# --- Resolve Blender binary ---
if [[ -z "$BLENDER_BIN" ]]; then
    BLENDER_BIN="$(command -v blender || true)"
fi
if [[ -z "$BLENDER_BIN" || ! -x "$BLENDER_BIN" ]]; then
    echo "error: blender binary not found on PATH.  Either install Blender" >&2
    echo "       or pass --blender /path/to/blender." >&2
    exit 1
fi

# --- Absolutize paths (Blender's background mode runs in its own CWD) ---
BLEND_ABS="$(cd "$(dirname "$BLEND")" && pwd)/$(basename "$BLEND")"
if [[ -z "$OUT" ]]; then
    OUT="$(dirname "$BLEND_ABS")/renders"
fi
mkdir -p "$OUT"
OUT_ABS="$(cd "$OUT" && pwd)"

# --- Run ---
echo "==> Rendering stationary cameras in $BLEND_ABS"
echo "    blender    : $BLENDER_BIN"
echo "    out dir    : $OUT_ABS"
echo "    samples    : $SAMPLES"
echo "    resolution : ${WIDTH}x${HEIGHT}"
echo "    device     : $DEVICE"
[[ "$NO_COMP" == 1 ]] && echo "    compositor : DISABLED (--no-compositor)"

NO_COMP_FLAG=()
[[ "$NO_COMP" == 1 ]] && NO_COMP_FLAG=(--no-compositor)

exec "$BLENDER_BIN" \
    --background "$BLEND_ABS" \
    --python-exit-code 1 \
    --python "$RENDER_PY" -- \
    --out "$OUT_ABS" \
    --samples "$SAMPLES" \
    --width "$WIDTH" --height "$HEIGHT" \
    --device "$DEVICE" \
    "${NO_COMP_FLAG[@]}"
