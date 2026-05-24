#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run.sh — convenience wrapper for ddgeoviztools
#
# Automatically builds (or rebuilds) the Docker image whenever Dockerfile,
# requirements.txt, or any file under src/ changes.
#
# Usage:
#   ./run.sh split        /data/MAIA_260226.gdml --output-dir /data/split/
#   ./run.sh convert      /data/MAIA_260226.gdml --output /data/MAIA.gltf
#   ./run.sh split-convert /data/MAIA_260226.gdml --output-dir /data/output/
#   ./run.sh blender-scene /data/output/ --output /data/scene.blend
#   ./run.sh --help
# ---------------------------------------------------------------------------

set -euo pipefail

IMAGE="ddgeoviztools"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Compute a hash of every file that affects the image build so we know when
# to rebuild.  The hash is stored as a Docker image label "build.src_hash".
# ---------------------------------------------------------------------------
SRC_HASH=$(
    find "$SCRIPT_DIR/src" \
         "$SCRIPT_DIR/Dockerfile" \
         "$SCRIPT_DIR/requirements.txt" \
         -type f | sort | xargs md5sum 2>/dev/null | md5sum | cut -d' ' -f1
)

IMG_HASH=$(docker image inspect "$IMAGE" \
               --format '{{index .Config.Labels "build.src_hash"}}' \
               2>/dev/null || true)

if [ "$SRC_HASH" != "$IMG_HASH" ]; then
    echo "==> Building Docker image '$IMAGE' (source changed) ..."
    docker build -t "$IMAGE" \
        --label "build.src_hash=$SRC_HASH" \
        "$SCRIPT_DIR"
    echo "==> Build complete."
fi

# Run — mount current working directory as /data inside the container.
# Also mount a host-side logs directory to /tmp so that Blender's crash log
# (written to /tmp/blender.crash.txt by the kernel on SIGSEGV) is preserved
# on the host even though the container exits immediately.
LOGS_DIR="$(pwd)/blender-logs"
mkdir -p "$LOGS_DIR"
exec docker run --rm \
    -v "$(pwd):/data" \
    -v "$LOGS_DIR:/tmp" \
    "$IMAGE" "$@"
