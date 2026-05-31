#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# bake_web.sh — produce the baked detector GLB for the web viewer.
#
#   committed GLTF  ->  blender-scene (.blend)  ->  Cycles bake  ->  GLB
#
# Starts from the committed sub-detector GLTFs (no GDML step) and runs entirely
# headlessly in the ddgeoviztools Docker image. Output lands in web/public/baked/
# (detector_baked.glb + manifest.json), which the web build picks up.
#
# Usage:
#   ./scripts/bake_web.sh [MODELS_DIR]      # default web/public/models
# Env:
#   DDGEOVIZ_IMAGE    docker image tag        (default ddgeoviztools)
#   BAKE_RESOLUTION   lightmap px per object  (default 1024)
#   BAKE_SAMPLES      Cycles samples          (default 256)
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${DDGEOVIZ_IMAGE:-ddgeoviztools}"
SAMPLES="${BAKE_SAMPLES:-128}"
MODELS="${1:-web/public/models}"

mkdir -p "$ROOT/build/baked" "$ROOT/web/public/baked"

# 1. Build the image on demand (CI usually pre-builds it with layer caching).
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "==> building $IMAGE"
  docker build -t "$IMAGE" "$ROOT"
fi

# 2. GLTF -> scene.blend (materials + lights + phi cutaway). bpy + trimesh only.
echo "==> blender-scene from $MODELS"
docker run --rm -e DDGEOVIZTOOLS_DENOISE=0 -v "$ROOT:/data" -w /data "$IMAGE" \
  blender-scene "/data/$MODELS" --output /data/build/scene.blend --format gltf

# 3. Cycles AO bake -> build/baked/{detector_baked.glb, manifest.json}
echo "==> bake Cycles ambient occlusion (${SAMPLES} samples)"
docker run --rm --entrypoint blender -v "$ROOT:/data" -w /data "$IMAGE" \
  --background /data/build/scene.blend --python-exit-code 1 \
  --python /data/scripts/bake_lightmaps.py -- \
  --output-dir /data/build/baked --samples "$SAMPLES"

# 4. Publish only the self-contained GLB + manifest into the web public dir.
cp "$ROOT/build/baked/detector_baked.glb" "$ROOT/web/public/baked/"
cp "$ROOT/build/baked/manifest.json" "$ROOT/web/public/baked/"
echo "==> baked assets ready in web/public/baked/"
