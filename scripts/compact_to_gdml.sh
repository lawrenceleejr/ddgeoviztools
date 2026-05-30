#!/usr/bin/env bash
# compact_to_gdml.sh — convert a DD4hep compact XML detector to GDML,
# running DD4hep inside a Docker container (no local DD4hep install needed).
#
# DD4hep's geoConverter reads the compact XML (which usually XInclude's
# materials / segmentations / sub-detector descriptions from the same
# directory tree) and emits a single self-contained GDML.  This script
# bind-mounts the compact's parent directory into the container so all
# relative includes resolve.
#
# Usage:
#   scripts/compact_to_gdml.sh COMPACT.xml [options]
#
# Options:
#   -o, --out PATH       Output GDML path (default: same dir as input,
#                        same basename with a .gdml extension).
#       --image NAME     Docker image with DD4hep installed
#                        (default: ghcr.io/muoncollidersoft/mucoll-sim-alma9:v2.9.7).
#       --pull           docker pull the image before running.
#       --shell          Drop into a bash shell inside the container with
#                        the compact and output mounts in place — handy
#                        for debugging XInclude / plugin errors.
#   -h, --help           Show this help and exit.
#
# Examples:
#   scripts/compact_to_gdml.sh MAIA_compact/MAIA.xml
#   scripts/compact_to_gdml.sh MAIA.xml -o /tmp/MAIA.gdml
#   scripts/compact_to_gdml.sh MAIA.xml --image ghcr.io/aidasoft/dd4hep:latest
#   scripts/compact_to_gdml.sh MAIA.xml --shell

set -euo pipefail

usage() {
    sed -n '2,/^set -e/p' "$0" | sed -n '/^#/p' | sed 's/^# \{0,1\}//' | sed '$d'
    exit "${1:-0}"
}

# --- Defaults ---
COMPACT=""
OUT=""
IMAGE="ghcr.io/muoncollidersoft/mucoll-sim-alma9:v2.9.7"
DO_PULL=0
DROP_SHELL=0

# --- Parse args ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)   usage 0 ;;
        -o|--out)    OUT="$2"; shift 2 ;;
        --image)     IMAGE="$2"; shift 2 ;;
        --pull)      DO_PULL=1; shift ;;
        --shell)     DROP_SHELL=1; shift ;;
        --)          shift; break ;;
        -*)          echo "unknown option: $1" >&2; usage 2 ;;
        *)
            if [[ -z "$COMPACT" ]]; then
                COMPACT="$1"
            else
                echo "unexpected extra argument: $1" >&2
                usage 2
            fi
            shift
            ;;
    esac
done

if [[ -z "$COMPACT" && "$DROP_SHELL" == 0 ]]; then
    echo "error: missing COMPACT.xml path" >&2
    usage 2
fi
if [[ -n "$COMPACT" && ! -f "$COMPACT" ]]; then
    echo "error: not a file: $COMPACT" >&2
    exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
    echo "error: docker not found on PATH.  Install Docker to use compact_to_gdml.sh." >&2
    exit 1
fi

# --- Resolve absolute paths (Docker bind mounts can't be relative) ---
if [[ -n "$COMPACT" ]]; then
    COMPACT_DIR="$(cd "$(dirname "$COMPACT")" && pwd)"
    COMPACT_NAME="$(basename "$COMPACT")"
else
    COMPACT_DIR="$(pwd)"
    COMPACT_NAME=""
fi

if [[ -z "$OUT" ]]; then
    # Default: alongside the compact, replacing .xml with .gdml
    OUT="${COMPACT%.xml}.gdml"
    if [[ "$OUT" == "$COMPACT" ]]; then
        OUT="${COMPACT}.gdml"
    fi
fi
mkdir -p "$(dirname "$OUT")"
OUT_DIR="$(cd "$(dirname "$OUT")" && pwd)"
OUT_NAME="$(basename "$OUT")"

# --- Pull image if requested ---
if [[ "$DO_PULL" == 1 ]]; then
    echo "==> Pulling Docker image '$IMAGE' ..."
    docker pull "$IMAGE"
fi

# --- Run ---
MOUNTS=(
    -v "$COMPACT_DIR:/compact:ro"
    -v "$OUT_DIR:/out"
)

if [[ "$DROP_SHELL" == 1 ]]; then
    echo "==> Opening shell inside '$IMAGE'"
    echo "    compact dir : /compact (ro)   <- $COMPACT_DIR"
    echo "    out dir     : /out             <- $OUT_DIR"
    [[ -n "$COMPACT_NAME" ]] && echo "    compact file: /compact/$COMPACT_NAME"
    echo "    To run the conversion by hand:"
    echo "        geoConverter -compact2gdml in=file:/compact/$COMPACT_NAME out=/out/$OUT_NAME"
    exec docker run --rm -it "${MOUNTS[@]}" -w /compact "$IMAGE" /bin/bash
fi

echo "==> Converting DD4hep compact -> GDML"
echo "    image       : $IMAGE"
echo "    compact     : $COMPACT_DIR/$COMPACT_NAME"
echo "    output GDML : $OUT_DIR/$OUT_NAME"

# Use bash -lc so the image's login profile (which is where AIDASoft /
# Key4hep images source the DD4hep environment) is honoured.  The
# converter is then invoked with file:URLs to keep DD4hep's XInclude
# resolver happy with relative paths inside the compact directory tree.
exec docker run --rm \
    "${MOUNTS[@]}" \
    -w /compact \
    "$IMAGE" \
    /bin/bash -lc \
        "geoConverter -compact2gdml in=file:/compact/$COMPACT_NAME out=/out/$OUT_NAME"
