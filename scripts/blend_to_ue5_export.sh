#!/usr/bin/env bash
# blend_to_ue5_export.sh — export a detector .blend to UE5-ready per-sub-detector
# GLTF + manifest.json (meshes + Blender light rig + cameras), using the
# ddgeoviztools Docker image (no local Blender required).
#
# This is step 2 of the Blender -> UE5 pipeline.  The output directory is then
# consumed by ColliderVis/Tools/ue5_build_content.py inside the UE5 editor
# (run it from the editor's Python console).
#
# Usage:
#   scripts/blend_to_ue5_export.sh scene.blend [options]
#
# Options:
#   -o, --out DIR     Output directory (default: <blend-dir>/ue5_meshes/).
#       --collection N  Blender collection to export as meshes (default: Detector).
#       --no-lights     Skip exporting the Blender light rig to the manifest.
#       --no-cameras    Skip exporting cameras to the manifest.
#       --image NAME    Override Docker image tag (default: ddgeoviztools).
#       --no-build      Skip the image build / staleness check; just run.
#   -h, --help          Show this help and exit.
#
# Examples:
#   scripts/blend_to_ue5_export.sh /tmp/detector.blend
#   scripts/blend_to_ue5_export.sh detector.blend -o /tmp/ue5_meshes
#   scripts/blend_to_ue5_export.sh detector.blend --no-cameras

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOOLS_DIR="$REPO_ROOT/ColliderVis/Tools"
EXPORT_PY_HOST="$TOOLS_DIR/blend_to_ue5.py"

usage() {
    sed -n '2,/^set -e/p' "$0" | sed -n '/^#/p' | sed 's/^# \{0,1\}//' | sed '$d'
    exit "${1:-0}"
}

# --- Defaults ---
OUT=""
COLLECTION="Detector"
IMAGE="ddgeoviztools"
DO_BUILD=1
BLEND=""
EXTRA_FLAGS=()

# --- Parse args ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)     usage 0 ;;
        -o|--out)      OUT="$2"; shift 2 ;;
        --collection)  COLLECTION="$2"; shift 2 ;;
        --no-lights)   EXTRA_FLAGS+=(--no-lights); shift ;;
        --no-cameras)  EXTRA_FLAGS+=(--no-cameras); shift ;;
        --image)       IMAGE="$2"; shift 2 ;;
        --no-build)    DO_BUILD=0; shift ;;
        --)            shift; break ;;
        -*)            echo "unknown option: $1" >&2; usage 2 ;;
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
if [[ ! -f "$EXPORT_PY_HOST" ]]; then
    echo "error: blend_to_ue5.py not found at: $EXPORT_PY_HOST" >&2
    exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
    echo "error: docker not found on PATH.  Install Docker to use blend_to_ue5_export.sh." >&2
    exit 1
fi

# --- Absolutize host paths (Docker can't bind relative paths) ---
BLEND_HOST_DIR="$(cd "$(dirname "$BLEND")" && pwd)"
BLEND_NAME="$(basename "$BLEND")"

if [[ -z "$OUT" ]]; then
    OUT="$BLEND_HOST_DIR/ue5_meshes"
fi
mkdir -p "$OUT"
OUT_HOST="$(cd "$OUT" && pwd)"

# --- Build (or rebuild) the Docker image if src/Dockerfile/requirements
#     changed since the last build (mirrors run.sh / quick_render.sh). ---
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

# --- Mounts ---
#   /blend (ro)   the directory containing the .blend
#   /tools (ro)   ColliderVis/Tools so blend_to_ue5.py is reachable
#   /out          writable output dir for GLTF + manifest.json
MOUNTS=(
    -v "$BLEND_HOST_DIR:/blend:ro"
    -v "$TOOLS_DIR:/tools:ro"
    -v "$OUT_HOST:/out"
)

echo "==> Exporting $BLEND_NAME to UE5 GLTF + manifest"
echo "    image      : $IMAGE"
echo "    collection : $COLLECTION"
echo "    out dir    : $OUT_HOST"

docker run --rm \
    --entrypoint blender \
    "${MOUNTS[@]}" \
    "$IMAGE" \
    --background "/blend/$BLEND_NAME" \
    --python-exit-code 1 \
    --python /tools/blend_to_ue5.py -- \
    --output-dir /out \
    --collection "$COLLECTION" \
    ${EXTRA_FLAGS[@]+"${EXTRA_FLAGS[@]}"}

echo ""
echo "  ✓  Export complete: $OUT_HOST"
echo "     Next: in the UE5 editor run"
echo "       ColliderVis/Tools/ue5_build_content.py --manifest-dir $OUT_HOST"
