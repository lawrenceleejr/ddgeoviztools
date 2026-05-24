#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build_mac.sh  —  Build ColliderVis as a standalone macOS application
#
# Usage:
#   ./scripts/build_mac.sh                      # Shipping build (default)
#   BUILD_CONFIG=Development ./scripts/build_mac.sh
#   UE5_ROOT="/path/to/UE_5.4" ./scripts/build_mac.sh
#
# The output is a self-contained ColliderVis.app bundle in Builds/Mac/.
# Double-click it to run, or share the .app with collaborators.
#
# For tethered Meta Quest 3 (PCVR via Quest Link):
#   1. Install Meta Quest Link on Mac (requires macOS 12+).
#   2. Connect your Quest 3 via USB-C or Wi-Fi Air Link.
#   3. Launch the built app — it will automatically use the Quest as the display.
#   4. In-game: VR mode is NOT the default for Mac builds.
#      To start in VR, set World Settings > GameMode Override to
#      ColliderVisVRGameMode before packaging, or append to the launch command:
#        ColliderVis.app/Contents/MacOS/ColliderVis
#            -game /Script/ColliderVis.ColliderVisVRGameMode
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
UE5_ROOT="${UE5_ROOT:-/Users/Shared/Epic Games/UE_5.4}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/../ColliderVis"
PROJECT_FILE="$PROJECT_DIR/ColliderVis.uproject"
OUTPUT_DIR="$SCRIPT_DIR/../Builds/Mac"
CONFIG="${BUILD_CONFIG:-Shipping}"
# ─────────────────────────────────────────────────────────────────────────────

UAT="$UE5_ROOT/Engine/Build/BatchFiles/RunUAT.sh"

if [[ ! -f "$UAT" ]]; then
    echo ""
    echo "  ERROR: RunUAT.sh not found at:"
    echo "    $UAT"
    echo ""
    echo "  Set UE5_ROOT to your Unreal Engine 5 installation directory, e.g.:"
    echo "    UE5_ROOT=\"/Users/Shared/Epic Games/UE_5.4\" ./scripts/build_mac.sh"
    echo ""
    exit 1
fi

if [[ ! -f "$PROJECT_FILE" ]]; then
    echo "  ERROR: Project file not found: $PROJECT_FILE"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo ""
echo "  ┌─────────────────────────────────────────┐"
echo "  │  ColliderVis → macOS standalone (.app)  │"
echo "  └─────────────────────────────────────────┘"
echo "  Config  : $CONFIG"
echo "  Project : $PROJECT_FILE"
echo "  Output  : $OUTPUT_DIR"
echo ""

"$UAT" BuildCookRun \
    -project="$PROJECT_FILE" \
    -platform=Mac \
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
echo "  App location: $OUTPUT_DIR/Mac/ColliderVis.app"
echo ""
echo "  ── Run desktop mode ────────────────────────────────────────────────"
echo "    open \"$OUTPUT_DIR/Mac/ColliderVis.app\""
echo ""
echo "  ── Run in VR mode (tethered Quest 3 via Quest Link) ────────────────"
echo "    \"$OUTPUT_DIR/Mac/ColliderVis.app/Contents/MacOS/ColliderVis\""
echo "      -game ColliderVisVRGameMode"
echo ""
