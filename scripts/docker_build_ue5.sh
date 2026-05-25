#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# docker_build_ue5.sh  —  Build and compile ColliderVis inside a UE5 Linux
#                         Docker container for headless build diagnosis.
#
# Usage:
#   ./scripts/docker_build_ue5.sh               # Development build (default)
#   BUILD_CONFIG=Shipping ./scripts/docker_build_ue5.sh
#   UE_VERSION=5.7 ./scripts/docker_build_ue5.sh
#
# Prerequisites (one-time):
#   1. Link your Epic Games account to GitHub:
#        https://www.epicgames.com/id/linked-accounts
#   2. Accept the UE source-code licence on GitHub:
#        https://github.com/EpicGames/UnrealEngine  →  "Join the organization"
#   3. Log in to ghcr.io with a GitHub PAT (read:packages scope):
#        docker login ghcr.io -u <your-github-username>
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
UE_VERSION="${UE_VERSION:-5.7}"
BUILD_CONFIG="${BUILD_CONFIG:-Development}"
IMAGE_TAG="collidervis-builder:${UE_VERSION}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_DIR="$REPO_ROOT/ColliderVis"
DOCKERFILE="$REPO_ROOT/Dockerfile.ue5build"
# ─────────────────────────────────────────────────────────────────────────────

if [[ ! -f "$PROJECT_DIR/ColliderVis.uproject" ]]; then
    echo "  ERROR: ColliderVis.uproject not found under $PROJECT_DIR"
    exit 1
fi

echo ""
echo "  ┌──────────────────────────────────────────────────────────────────┐"
echo "  │  ColliderVis — headless Linux C++ build (UE ${UE_VERSION}, Docker)      │"
echo "  └──────────────────────────────────────────────────────────────────┘"
echo "  Config     : $BUILD_CONFIG"
echo "  UE version : $UE_VERSION"
echo "  Image tag  : $IMAGE_TAG"
echo "  Project    : $PROJECT_DIR"
echo ""

# ── Step 1: Build the Docker image ────────────────────────────────────────────
echo "  [1/2] Building Docker image..."
echo "        (pulls ghcr.io/epicgames/unreal-engine:${UE_VERSION}-dev-slim on first run)"
echo "        If this fails with 'denied', complete the ghcr.io login described"
echo "        in the Prerequisites section at the top of this script."
echo ""

docker build \
    --build-arg "UE_VERSION=${UE_VERSION}" \
    -f "$DOCKERFILE" \
    -t "$IMAGE_TAG" \
    "$REPO_ROOT"

echo ""
echo "  [2/2] Running C++ compile inside container..."
echo ""

# ── Step 2: Run the compile ───────────────────────────────────────────────────
# The project source is mounted read-write so UBT can write intermediate files
# (Binaries/, Intermediate/) into the local tree — identical to a native build.
docker run --rm \
    -e "BUILD_CONFIG=${BUILD_CONFIG}" \
    -v "${PROJECT_DIR}:/project/ColliderVis" \
    "$IMAGE_TAG"

echo ""
echo "  ✓  Build complete (config: ${BUILD_CONFIG})."
echo "     Binaries are in ColliderVis/Binaries/ and ColliderVis/Intermediate/"
echo ""
echo "  ── Diagnose a specific error ───────────────────────────────────────"
echo "  Drop into a shell inside the container:"
echo ""
echo "    docker run --rm -it \\"
echo "      -v \"\$(pwd)/ColliderVis:/project/ColliderVis\" \\"
echo "      $IMAGE_TAG bash"
echo ""
echo "  Then run the build manually:"
echo "    \$UE_ROOT/Engine/Build/BatchFiles/Linux/Build.sh \\"
echo "        ColliderVis Linux Development \\"
echo "        /project/ColliderVis/ColliderVis.uproject \\"
echo "        -waitmutex -NoHotReload 2>&1 | tee /tmp/build.log"
echo ""
