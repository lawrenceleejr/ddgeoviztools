#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build_linux.sh  —  Build ColliderVis as a Linux standalone binary
#
# Usage:
#   ./scripts/build_linux.sh                    # Shipping build (default)
#   BUILD_CONFIG=Development ./scripts/build_linux.sh
#   UE5_ROOT="/path/to/UE_5.4" ./scripts/build_linux.sh
#
# This script is designed to run either:
#   • Natively on a Linux machine with Unreal Engine installed from source
#   • Inside the collidervis-builder Docker container (see docker_build_ue5.sh)
#     In that case UE5_ROOT is automatically set to $UE_ROOT from the image.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
# Inside the Docker image the engine lives at $UE_ROOT; fall back to a
# user-supplied path or the standard source-build location.
UE5_ROOT="${UE5_ROOT:-${UE_ROOT:-/home/ue4/UnrealEngine}}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/../ColliderVis"
PROJECT_FILE="$PROJECT_DIR/ColliderVis.uproject"
OUTPUT_DIR="$SCRIPT_DIR/../Builds/Linux"
CONFIG="${BUILD_CONFIG:-Shipping}"
# ─────────────────────────────────────────────────────────────────────────────

UAT="$UE5_ROOT/Engine/Build/BatchFiles/RunUAT.sh"

if [[ ! -f "$UAT" ]]; then
    echo ""
    echo "  ERROR: RunUAT.sh not found at:"
    echo "    $UAT"
    echo ""
    echo "  Set UE5_ROOT to your Unreal Engine 5 installation directory, e.g.:"
    echo "    UE5_ROOT=\"/home/ue4/UnrealEngine\" ./scripts/build_linux.sh"
    echo ""
    echo "  To build inside Docker instead, use:"
    echo "    ./scripts/docker_build_ue5.sh"
    echo ""
    exit 1
fi

if [[ ! -f "$PROJECT_FILE" ]]; then
    echo "  ERROR: Project file not found: $PROJECT_FILE"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo ""
echo "  ┌─────────────────────────────────────────────────┐"
echo "  │  ColliderVis → Linux standalone (x86_64)        │"
echo "  └─────────────────────────────────────────────────┘"
echo "  Config  : $CONFIG"
echo "  Project : $PROJECT_FILE"
echo "  Output  : $OUTPUT_DIR"
echo ""

"$UAT" BuildCookRun \
    -project="$PROJECT_FILE" \
    -platform=Linux \
    -clientconfig="$CONFIG" \
    -cook \
    -build \
    -stage \
    -pak \
    -archive \
    -archivedirectory="$OUTPUT_DIR" \
    -noxge \
    -noP4 \
    -utf8output

echo ""
echo "  ✓  Build complete."
echo "  Binary location: $OUTPUT_DIR/Linux/ColliderVis"
echo ""
