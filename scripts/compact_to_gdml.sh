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
#                        (default: ghcr.io/muoncollidersoft/mucoll-sim-alma9:legacy-2.x).
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
IMAGE="ghcr.io/muoncollidersoft/mucoll-sim-alma9:legacy-2.x"
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
    exec docker run --rm -it \
        --entrypoint /bin/bash \
        "${MOUNTS[@]}" \
        -w /compact \
        "$IMAGE"
fi

echo "==> Converting DD4hep compact -> GDML"
echo "    image       : $IMAGE"
echo "    compact     : $COMPACT_DIR/$COMPACT_NAME"
echo "    output GDML : $OUT_DIR/$OUT_NAME"

# HEP simulation images (muoncollidersoft, AIDASoft, Key4hep, …) generally
# require an explicit ``source <init.sh>`` to put geoConverter / DD4hep on
# PATH — even a login shell isn't always enough, since they don't always
# drop hooks into /etc/profile.d.
#
# Search the common init-script locations in priority order; the first
# match wins.  ``DDGDML_INIT`` env var on the host overrides everything
# (the script is passed through to the container so users with custom
# images can point at any init file).
INIT_OVERRIDE="${DDGDML_INIT:-}"
INIT_BLOCK='
set +e

# 0) Muon Collider images expose a one-shot setup:
#    - mucoll-sim-ubuntu24 (v2.11+):  source setup_spack.sh, then
#                                     source /opt/setup_mucoll.sh
#    - mucoll-sim-alma9    (v2.9.x):  call the setup_mucoll function
#    Spack first (so its view dirs land on PATH / LD_LIBRARY_PATH),
#    then mucoll on top.  Source-based form for the current default
#    image; function-call fallback for older images.
for spack in /opt/setup_spack.sh /opt/spack/share/spack/setup-env.sh; do
    if [ -f "$spack" ]; then
        source "$spack"
        break
    fi
done
if [ -f /opt/setup_mucoll.sh ]; then
    source /opt/setup_mucoll.sh
fi
for cmd in setup_mucoll key4hep_nightly key4hep_release; do
    if type "$cmd" >/dev/null 2>&1; then
        "$cmd" >/dev/null 2>&1 || true
    fi
done

# 0b) Diagnostic: dump the key library-path env vars that the DD4hep
#     plugin loader consults.  If geoConverter later fails with "bad
#     any_cast" / "No factory" this dump shows what was reachable.
echo "    LD_LIBRARY_PATH:"
echo "${LD_LIBRARY_PATH:-}" | tr ":" "\n" | sed "s/^/        /"
echo "    DD4HEP_LIBRARY_PATH:"
echo "${DD4HEP_LIBRARY_PATH:-}" | tr ":" "\n" | sed "s/^/        /"

# 1) Honour DDGDML_INIT override on the host if it points at a real file.
if [ -n "'"$INIT_OVERRIDE"'" ] && [ -f "'"$INIT_OVERRIDE"'" ]; then
    source "'"$INIT_OVERRIDE"'"
fi

# 2) Try the common HEP / Muon Collider / Spack-env init scripts.
for s in \
    /opt/ilcsoft/muonc/init_ilcsoft.sh \
    /opt/ilcsoft/init_ilcsoft.sh \
    /opt/MuonCollider/setup.sh \
    /opt/spack-environments/*/activate.sh \
    /opt/spack-environment/activate.sh \
    /opt/spack/share/spack/setup-env.sh \
    /opt/setup.sh \
    /setup.sh \
    /usr/local/setup.sh \
    /opt/*/setup.sh \
    /opt/*/bin/thisdd4hep.sh; do
    [ -f "$s" ] && source "$s" 2>/dev/null
done

# 3) Last-ditch: locate the geoConverter binary on the filesystem and
#    source its neighbouring init script + prepend its dir to PATH.
if ! command -v geoConverter >/dev/null 2>&1; then
    GC=$(find /opt /usr/local /usr -maxdepth 8 -name geoConverter \
            -type f -executable 2>/dev/null | head -1)
    if [ -n "$GC" ]; then
        BIN_DIR=$(dirname "$GC")
        PREFIX=$(dirname "$BIN_DIR")
        for s in "$BIN_DIR/thisdd4hep.sh" \
                 "$PREFIX/bin/thisdd4hep.sh" \
                 "$PREFIX/setup.sh" \
                 "$PREFIX/init.sh"; do
            [ -f "$s" ] && source "$s" 2>/dev/null
        done
        export PATH="$BIN_DIR:$PATH"
    fi
fi

set -e

if ! command -v geoConverter >/dev/null 2>&1; then
    echo "error: geoConverter not on PATH after env init." >&2
    echo "       /opt contents:" >&2
    ls -1 /opt 2>/dev/null | sed "s/^/         /" >&2
    echo "       Re-run with --shell to investigate, or set DDGDML_INIT=" >&2
    echo "       on the host to a known-good init script path inside the container." >&2
    exit 1
fi
echo "    geoConverter at: $(command -v geoConverter)"
'

# Override the image's ENTRYPOINT — several of these stacks set
# ENTRYPOINT=/bin/bash, which would otherwise eat our command and try
# to exec /bin/bash as a script.
exec docker run --rm \
    --entrypoint /bin/bash \
    "${MOUNTS[@]}" \
    -w /compact \
    "$IMAGE" \
    -lc "$INIT_BLOCK
geoConverter -compact2gdml -input /compact/$COMPACT_NAME -output /out/$OUT_NAME"
