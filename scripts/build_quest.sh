#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build_quest.sh  —  Build ColliderVis as a Meta Quest 3 standalone APK
#
# Usage:
#   ./scripts/build_quest.sh                    # Shipping build (default)
#   BUILD_CONFIG=Development ./scripts/build_quest.sh
#   UE5_ROOT="/path/to/UE_5.7" ./scripts/build_quest.sh
#
# Prerequisites (one-time setup — see UE5_SETUP.md § Android Packaging):
#   1. Android Studio + NDK r25b installed
#   2. UE5 Project Settings → Platforms → Android configured
#   3. Meta Quest developer mode enabled on the headset
#   4. adb (Android Debug Bridge) on your PATH to side-load the APK
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
# Adjust UE5_ROOT to match your Unreal Engine 5 installation.
# Common locations:
#   macOS:   /Users/Shared/Epic\ Games/UE_5.7
#   Linux:   ~/UnrealEngine  (if built from source)
#   Windows: C:\Program Files\Epic Games\UE_5.7  (use build_quest.bat instead)
UE5_ROOT="${UE5_ROOT:-/Users/Shared/Epic Games/UE_5.7}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/../ColliderVis"
PROJECT_FILE="$PROJECT_DIR/ColliderVis.uproject"
OUTPUT_DIR="$SCRIPT_DIR/../Builds/Quest3"
CONFIG="${BUILD_CONFIG:-Shipping}"
# ─────────────────────────────────────────────────────────────────────────────

UAT="$UE5_ROOT/Engine/Build/BatchFiles/RunUAT.sh"

if [[ ! -f "$UAT" ]]; then
    echo ""
    echo "  ERROR: RunUAT.sh not found at:"
    echo "    $UAT"
    echo ""
    echo "  Set UE5_ROOT to your Unreal Engine 5 installation directory, e.g.:"
    echo "    UE5_ROOT=\"/Users/Shared/Epic Games/UE_5.7\" ./scripts/build_quest.sh"
    echo ""
    exit 1
fi

if [[ ! -f "$PROJECT_FILE" ]]; then
    echo "  ERROR: Project file not found: $PROJECT_FILE"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo ""
echo "  ┌─────────────────────────────────────────────┐"
echo "  │  ColliderVis → Meta Quest 3 (Android ARM64) │"
echo "  └─────────────────────────────────────────────┘"
echo "  Config  : $CONFIG"
echo "  Project : $PROJECT_FILE"
echo "  Output  : $OUTPUT_DIR"
echo ""

# BuildCookRun flags:
#   -platform=Android          Target Android
#   -cookflavor=ASTC           ASTC texture compression (Quest 3 requirement)
#   -clientconfig=Shipping     Optimised release build (no debug overhead)
#   -cook                      Cook content (convert assets to runtime format)
#   -build                     Compile game code
#   -stage                     Gather cooked content into staging directory
#   -pak                       Package into .pak files
#   -archive                   Copy final package to -archivedirectory
#   -noxge / -noP4             Skip XGE and Perforce (not used here)
"$UAT" BuildCookRun \
    -project="$PROJECT_FILE" \
    -platform=Android \
    -clientconfig="$CONFIG" \
    -cookflavor=ASTC \
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
echo "  APK location: $OUTPUT_DIR/Android_ASTC/"
echo ""
echo "  ── Install to an attached Quest 3 ──────────────────────────────────"
echo "  Make sure the headset is connected via USB and developer mode is on,"
echo "  then run:"
echo ""
echo "    adb install \"$OUTPUT_DIR/Android_ASTC/ColliderVis-arm64.apk\""
echo ""
echo "  Or use Meta Quest Developer Hub to drag-and-drop the APK."
echo ""
echo "  ── Wireless install (Quest Air Link) ───────────────────────────────"
echo "    adb connect <headset-ip>:5555"
echo "    adb install \"$OUTPUT_DIR/Android_ASTC/ColliderVis-arm64.apk\""
echo ""
