#!/usr/bin/env bash
#
# render_lumen_mrq.sh — headless Movie Render Queue (Lumen) render for ColliderVis
# ------------------------------------------------------------------------------
# Renders high-quality offline Lumen (hardware-ray-traced) stills/sequences of the
# ColliderVisMain level on macOS / Apple Silicon.
#
# The project's realtime defaults keep ray tracing OFF (DefaultEngine.ini, so the
# editor/PIE/game run fast). This render process turns the RT pipeline back ON for
# itself only, via -dpcvars at launch (see the ARGS block). On macOS 26+ / Apple
# Silicon the true hardware Path Tracer is now also available — see the path-tracer
# note in Tools/MOVIE_RENDER_QUEUE.md to switch this from Lumen-HWRT to path-traced.
#
# This drives `UnrealEditor-Cmd` in -game mode with the UE 5.8 Movie Render
# Pipeline command-line path (MovieRenderPipelineCommandLine.cpp), which auto-
# starts the render once the map loads when -LevelSequence + -MoviePipelineConfig
# are supplied.
#
# PREREQUISITE (one-time): the MRQ config + still sequence assets must exist.
# Generate them with the companion Python script:
#
#   "$UE/Engine/Binaries/Mac/UnrealEditor-Cmd" "$PROJECT" \
#       -run=pythonscript -script="$PWD/Tools/make_mrq_config.py" -unattended -nosplash
#
# (Or run this script with `--make-config` to do that step for you.)
#
# USAGE
#   chmod +x Tools/render_lumen_mrq.sh           # one-time
#   Tools/render_lumen_mrq.sh                     # render the default hero still
#   Tools/render_lumen_mrq.sh --make-config       # build config+sequence, then render
#   Tools/render_lumen_mrq.sh --seq /Game/Cinematics/LS_MyFlythrough  # custom sequence
#   Tools/render_lumen_mrq.sh --out /abs/path/renders --resx 7680 --resy 4320
#   Tools/render_lumen_mrq.sh --config /Game/Cinematics/MRQ_ColliderVis_Lumen4K
#
# FLAGS
#   --make-config        Run Tools/make_mrq_config.py first (builds assets), then render.
#   --config <pkg>       MoviePipeline config asset path  (default below)
#   --seq <pkg>          Level Sequence asset path        (default below)
#   --out <dir>          Output directory                 (default: <project>/renders)
#   --resx <n> --resy <n>  Override resolution (also bakes into -ForcedRes* / window)
#   --ue <dir>           Engine root (default: /Users/Shared/Epic Games/UE_5.8)
#   --dry-run            Print the command and exit (do not launch).
#   -h | --help          Show this help.
#
# OUTPUT
#   Frames land in the config's Output Directory. The bundled config uses the
#   token "{project_dir}/renders/" → resolves to <project>/renders/.
#   File name format: ColliderVis_{sequence_name}_{frame_number}.png  (or .exr)
#
# NOTE: Run ONLY when the interactive editor is closed (two editors at once is
#       too heavy and they fight over the project lock / shader cache).
# ------------------------------------------------------------------------------

set -euo pipefail

# --- Defaults -----------------------------------------------------------------
UE_ROOT="/Users/Shared/Epic Games/UE_5.8"
PROJECT_DIR="/Users/leejr/Work/ddgeoviztools/ColliderVis"
PROJECT="${PROJECT_DIR}/ColliderVis.uproject"
MAP="/Game/Maps/ColliderVisMain"

CONFIG="/Game/Cinematics/MRQ_ColliderVis_Lumen4K"
SEQUENCE="/Game/Cinematics/LS_ColliderVis_Still"
OUT_DIR="${PROJECT_DIR}/renders"
RESX=3840
RESY=2160
MAKE_CONFIG=0
DRY_RUN=0

usage() { sed -n '2,55p' "$0"; exit 0; }

# --- Parse args ---------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --make-config) MAKE_CONFIG=1; shift ;;
    --config)      CONFIG="$2";   shift 2 ;;
    --seq)         SEQUENCE="$2"; shift 2 ;;
    --out)         OUT_DIR="$2";  shift 2 ;;
    --resx)        RESX="$2";     shift 2 ;;
    --resy)        RESY="$2";     shift 2 ;;
    --ue)          UE_ROOT="$2";  shift 2 ;;
    --dry-run)     DRY_RUN=1;     shift ;;
    -h|--help)     usage ;;
    *) echo "Unknown arg: $1" >&2; echo "Run with --help." >&2; exit 2 ;;
  esac
done

CMD_BIN="${UE_ROOT}/Engine/Binaries/Mac/UnrealEditor-Cmd"

# --- Sanity checks ------------------------------------------------------------
[[ -x "$CMD_BIN" ]]    || { echo "ERROR: UnrealEditor-Cmd not found/executable at: $CMD_BIN" >&2; exit 1; }
[[ -f "$PROJECT" ]]    || { echo "ERROR: project not found at: $PROJECT" >&2; exit 1; }
mkdir -p "$OUT_DIR"

echo "=============================================================="
echo " ColliderVis — Movie Render Queue (Lumen, headless)"
echo "   Engine   : $UE_ROOT"
echo "   Project  : $PROJECT"
echo "   Map      : $MAP"
echo "   Sequence : $SEQUENCE"
echo "   Config   : $CONFIG"
echo "   Output   : $OUT_DIR  (config also writes {project_dir}/renders/)"
echo "   Res      : ${RESX}x${RESY}  (render res = config OutputResolution; the"
echo "              small RHI window below is just the required swapchain)"
echo "=============================================================="
echo "   NOTE: --resx/--resy here are informational. To change the actual"
echo "         render resolution, edit RES_X/RES_Y in Tools/make_mrq_config.py"
echo "         and re-run with --make-config (MRQ reads OutputResolution from"
echo "         the config asset, not from the command line)."

# --- Optionally build the config + sequence assets first ----------------------
if [[ "$MAKE_CONFIG" -eq 1 ]]; then
  echo ">> Building MRQ config + still sequence via make_mrq_config.py ..."
  MK=( "$CMD_BIN" "$PROJECT"
       -run=pythonscript
       -script="${PROJECT_DIR}/Tools/make_mrq_config.py"
       -unattended -nosplash -nullrhi )
  if [[ "$DRY_RUN" -eq 1 ]]; then printf '   %q ' "${MK[@]}"; echo; else "${MK[@]}"; fi
fi

# --- Build the render command -------------------------------------------------
# Flags explained:
#   "$PROJECT" "$MAP"                  project + map to load (map drives the scene)
#   -game                              MRQ command-line render requires -game mode
#   -LevelSequence / -MoviePipelineConfig   the two args that auto-trigger MRQ
#   -MoviePipelineLocalExecutorClass   in-process executor that quits when done
#   -windowed -resx/-resy              spawns a small RHI window (Metal needs a real
#                                      swapchain; -nullrhi must NOT be used for the
#                                      actual render — Lumen needs the GPU)
#   -notexturestreaming                full-res textures in every frame
#   -noloadingscreen -unattended       no UI prompts; auto-exit on completion/error
#   -log -stdout -FullStdOutLogOutput  stream the render log to the console
#   -dpcvars                           STARTUP cvars for THIS render process only:
#                                      turns the ray-tracing pipeline ON (r.RayTracing is
#                                      startup/read-only — must be set here, not via
#                                      -ExecCmds; project default is False).
#   -ExecCmds                          post-boot belt-and-braces (Lumen HWRT reflections on)
ARGS=(
  "$PROJECT" "$MAP"
  -game
  -LevelSequence="$SEQUENCE"
  -MoviePipelineConfig="$CONFIG"
  -MoviePipelineLocalExecutorClass=/Script/MovieRenderPipelineCore.MoviePipelineInProcessExecutor
  -windowed -resx=1280 -resy=720
  -notexturestreaming
  -noloadingscreen
  -unattended
  -nosplash
  -dpcvars="r.RayTracing=1,r.RayTracing.Shadows=1,r.Lumen.HardwareRayTracing=1,r.Lumen.Reflections.HardwareRayTracing=1"
  -ExecCmds="r.Lumen.HardwareRayTracing 1, r.Lumen.Reflections.HardwareRayTracing 1"
  -log
  -stdout
  -FullStdOutLogOutput
)

echo ">> Render command:"
printf '   %q ' "$CMD_BIN" "${ARGS[@]}"; echo
echo "--------------------------------------------------------------"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "(dry-run) not launching."
  exit 0
fi

# --- Launch -------------------------------------------------------------------
"$CMD_BIN" "${ARGS[@]}"
STATUS=$?

echo "--------------------------------------------------------------"
if [[ $STATUS -eq 0 ]]; then
  echo ">> Render finished OK. Frames in the config output dir (default: $OUT_DIR)."
  ls -lh "$OUT_DIR" 2>/dev/null || true
else
  echo ">> Render exited with status $STATUS. Check the log above." >&2
fi
exit $STATUS
