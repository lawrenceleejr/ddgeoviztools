#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run.sh — convenience wrapper for ddgeoviztools
#
# Automatically builds the Docker image on first use, then runs the container
# with the current directory mounted at /data.
#
# Usage:
#   ./run.sh split        /data/MAIA_260226.gdml --output-dir /data/split/
#   ./run.sh convert      /data/MAIA_260226.gdml --output /data/MAIA.gltf
#   ./run.sh split-convert /data/MAIA_260226.gdml --output-dir /data/output/
#   ./run.sh --help
# ---------------------------------------------------------------------------

set -euo pipefail

IMAGE="ddgeoviztools"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Build image if it does not exist yet (or if Dockerfile/requirements changed)
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "==> Building Docker image '$IMAGE' (first run — this may take a few minutes) ..."
    docker build -t "$IMAGE" "$SCRIPT_DIR"
    echo "==> Build complete."
fi

# Run — mount current working directory as /data inside the container
exec docker run --rm \
    -v "$(pwd):/data" \
    "$IMAGE" "$@"
