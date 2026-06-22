#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
make_mrq_config.py — build the Movie Render Queue (MRQ) assets that the
command-line render in Tools/render_lumen_mrq.sh consumes.

Run headless via:
    "/Users/Shared/Epic Games/UE_5.8/Engine/Binaries/Mac/UnrealEditor-Cmd" \
        "/Users/leejr/Work/ddgeoviztools/ColliderVis/ColliderVis.uproject" \
        -run=pythonscript -script="/Users/leejr/Work/ddgeoviztools/ColliderVis/Tools/make_mrq_config.py" \
        -unattended -nosplash

WHY THIS EXISTS
---------------
UE 5.8 command-line MRQ (MovieRenderPipelineCommandLine.cpp) requires:
  * a Level Sequence  ( -LevelSequence="/Game/..." ), AND
  * a config/queue asset OR exported manifest ( -MoviePipelineConfig="/Game/..." ).
There is NO pure-flags path that skips a pre-existing config asset; the engine
only loads a UMoviePipelinePrimaryConfig / UMoviePipelineQueue / text manifest.
So we generate both assets once, then the .sh just references them.

This script creates (idempotent — overwrites in place):
  /Game/Cinematics/MRQ_ColliderVis_Lumen4K   (UMoviePipelinePrimaryConfig)
  /Game/Cinematics/LS_ColliderVis_Still       (1-frame Level Sequence with a
                                                spawnable CineCamera framing the
                                                detector origin + camera-cut track)

The still sequence exists so a hero frame renders out-of-the-box even though the
project currently ships no authored Level Sequence (only BP_CineCamera). The
orchestrator can later author richer sequences and point the .sh at them; this
config asset is reusable across any of them.

VERIFIED against the 5.8 engine source (class + property names):
  MoviePipelinePrimaryConfig.h, MoviePipelineOutputSetting.h,
  MoviePipelineAntiAliasingSetting.h, MoviePipelineGameOverrideSetting.h,
  MoviePipelineConsoleVariableSetting.h, MoviePipelineDeferredPasses.h,
  MoviePipelineImageSequenceOutput.h (PNG), MoviePipelineEXROutput.h (EXR).
"""

import unreal

# ----------------------------------------------------------------------------
# Tunables (mirror Tools/MOVIE_RENDER_QUEUE.md "Hero still" preset)
# ----------------------------------------------------------------------------
CONFIG_PACKAGE   = "/Game/Cinematics"
CONFIG_NAME      = "MRQ_ColliderVis_Lumen4K"
SEQ_NAME         = "LS_ColliderVis_Still"

RES_X, RES_Y     = 3840, 2160
SPATIAL_SAMPLES  = 16
TEMPORAL_SAMPLES = 8
ENGINE_WARMUP    = 64
# Output dir: {project}/renders/  (resolved at render time by the {output_dir} the
# .sh passes through OutputSetting; here we default to the project "renders" folder).
OUTPUT_DIR_TOKEN = "{project_dir}/renders/"
FILE_NAME_FORMAT = "ColliderVis_{sequence_name}_{frame_number}"

# Use EXR instead of PNG by setting this True (the .sh can also override at runtime
# by editing the saved asset, but PNG is the friendly default deliverable).
USE_EXR = False

# Lumen / quality console variables (forced to offline quality). Mirrors the doc.
CVARS = {
    "r.Lumen.HardwareRayTracing": 1,
    "r.Lumen.Reflections.HardwareRayTracing": 1,
    "r.Lumen.TraceMeshSDFs": 1,
    "r.LumenScene.Lighting.Quality": 4,
    "r.Lumen.ScreenProbeGather.Quality": 4,
    "r.Lumen.Reflections.Quality": 4,
    "r.Lumen.Reflections.SmoothBias": 0.1,
    "r.LumenScene.Radiosity.Quality": 4,
    "r.RayTracing.Shadows": 1,
    "r.MotionBlurQuality": 4,
    "r.DepthOfFieldQuality": 4,
    "r.Tonemapper.Quality": 5,
    "r.VolumetricFog": 1,
    "r.VolumetricFog.GridPixelSize": 4,
    "r.VolumetricFog.GridSizeZ": 256,
    # Force EVERY scalability group to Cinematic (4) for non-realtime renders, so the
    # offline output is maximum quality regardless of the player's in-menu setting.
    "sg.ViewDistanceQuality": 4,
    "sg.AntiAliasingQuality": 4,
    "sg.ShadowQuality": 4,
    "sg.GlobalIlluminationQuality": 4,
    "sg.ReflectionQuality": 4,
    "sg.PostProcessQuality": 4,
    "sg.TextureQuality": 4,
    "sg.EffectsQuality": 4,
    "sg.FoliageQuality": 4,
    "sg.ShadingQuality": 4,
    # Max geometry/shadow fidelity.
    "r.Nanite": 1,
    "r.Shadow.Virtual.Enable": 1,
    "r.Shadow.Virtual.ResolutionLodBiasLocal": -1.0,
    "r.Lumen.Reflections.Allow": 1,
    "r.AmbientOcclusionLevels": 4,
}

# Where to point the auto-generated still camera (detector is at world origin).
CAM_LOCATION = unreal.Vector(2400.0, -2700.0, 1500.0)  # elevated 3/4 hero: detector + symmetric beamline
CAM_LOOK_AT  = unreal.Vector(0.0, 0.0, 150.0)
CAM_FOV      = 58.0

log = unreal.log
warn = unreal.log_warning


# ----------------------------------------------------------------------------
def _asset_tools():
    return unreal.AssetToolsHelpers.get_asset_tools()


def make_still_sequence():
    """Create a 1-frame Level Sequence with a spawnable CineCamera + camera cut."""
    full_path = "{}/{}".format(CONFIG_PACKAGE, SEQ_NAME)
    if unreal.EditorAssetLibrary.does_asset_exist(full_path):
        unreal.EditorAssetLibrary.delete_asset(full_path)

    seq = _asset_tools().create_asset(
        SEQ_NAME, CONFIG_PACKAGE,
        unreal.LevelSequence, unreal.LevelSequenceFactoryNew())

    # Display rate 24fps; 1-frame still: playback [0,1).
    seq.set_display_rate(unreal.FrameRate(24, 1))
    seq.set_playback_start(0)
    seq.set_playback_end(1)

    # Spawnable CineCamera so the render has a deterministic framing even with no
    # in-level camera. (Spawnable => owned by the sequence, no level dependency.)
    cam_binding = seq.add_spawnable_from_class(unreal.CineCameraActor)
    rot = unreal.MathLibrary.find_look_at_rotation(CAM_LOCATION, CAM_LOOK_AT)

    # Set the spawnable TEMPLATE's transform + FOV directly — reliable static pose.
    # (The per-channel track alone left the camera at the origin: in 5.8 the channel
    #  names carry a "_0" suffix, e.g. "Location.X_0", so exact "Location.X" never matched.)
    tmpl = cam_binding.get_object_template()
    tmpl.set_actor_location_and_rotation(CAM_LOCATION, rot, False, False)
    try:
        tmpl.get_cine_camera_component().set_field_of_view(CAM_FOV)
    except Exception as e:
        warn("[make_mrq_config] could not set FOV: {}".format(e))

    # Also key a transform track to match (uses startswith for the _0-suffixed names).
    transform_track = cam_binding.add_track(unreal.MovieScene3DTransformTrack)
    transform_section = transform_track.add_section()
    transform_section.set_start_frame_bounded(False)
    transform_section.set_end_frame_bounded(False)
    _vals = {"Location.X": CAM_LOCATION.x, "Location.Y": CAM_LOCATION.y, "Location.Z": CAM_LOCATION.z,
             "Rotation.X": rot.roll, "Rotation.Y": rot.pitch, "Rotation.Z": rot.yaw}
    for chan in transform_section.get_all_channels():
        n = chan.get_name()
        for key, val in _vals.items():
            if n.startswith(key):
                chan.add_key(unreal.FrameNumber(0), float(val)); break

    # Camera-cut track so MRQ renders through this camera.
    cut_track = seq.add_track(unreal.MovieSceneCameraCutTrack)
    cut_section = cut_track.add_section()
    cut_section.set_range(0, 1)
    # UE5.8: build the binding ID via the sequence extension (proxy has no
    # get_binding_id; the MovieSceneObjectBindingID(guid=...) ctor no longer matches).
    cut_section.set_camera_binding_id(
        unreal.MovieSceneSequenceExtensions.get_binding_id(seq, cam_binding))

    unreal.EditorAssetLibrary.save_asset(full_path)
    log("[make_mrq_config] Created still sequence: {}".format(full_path))
    return full_path


def make_config():
    """Create the reusable UMoviePipelinePrimaryConfig with Lumen/AA/output."""
    full_path = "{}/{}".format(CONFIG_PACKAGE, CONFIG_NAME)
    if unreal.EditorAssetLibrary.does_asset_exist(full_path):
        unreal.EditorAssetLibrary.delete_asset(full_path)

    config = _asset_tools().create_asset(
        CONFIG_NAME, CONFIG_PACKAGE,
        unreal.MoviePipelinePrimaryConfig,
        unreal.MoviePipelinePrimaryConfigFactory()
            if hasattr(unreal, "MoviePipelinePrimaryConfigFactory") else None)

    # ---- Output ----
    out = config.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    out.output_resolution = unreal.IntPoint(RES_X, RES_Y)
    out.output_directory = unreal.DirectoryPath(OUTPUT_DIR_TOKEN)
    out.file_name_format = FILE_NAME_FORMAT
    out.override_existing_output = True
    out.zero_pad_frame_numbers = 4

    # ---- Image output format (PNG or EXR) ----
    if USE_EXR:
        exr = config.find_or_add_setting_by_class(
            unreal.MoviePipelineImageSequenceOutput_EXR)
        try:
            exr.compression = unreal.EXRCompressionFormat.PIZ
            exr.multilayer = True
        except Exception as e:
            warn("[make_mrq_config] EXR option tweak skipped: {}".format(e))
    else:
        config.find_or_add_setting_by_class(
            unreal.MoviePipelineImageSequenceOutput_PNG)

    # ---- Deferred renderer pass (the standard Lumen-lit deferred pass) ----
    config.find_or_add_setting_by_class(unreal.MoviePipelineDeferredPassBase)

    # ---- Anti-aliasing / warmup (the quality knob) ----
    aa = config.find_or_add_setting_by_class(unreal.MoviePipelineAntiAliasingSetting)
    aa.spatial_sample_count = SPATIAL_SAMPLES
    aa.temporal_sample_count = TEMPORAL_SAMPLES
    aa.override_anti_aliasing = True
    aa.anti_aliasing_method = unreal.AntiAliasingMethod.AAM_NONE
    aa.use_camera_cut_for_warm_up = False
    aa.engine_warm_up_count = ENGINE_WARMUP
    aa.render_warm_up_frames = True

    # ---- Game overrides (keep AColliderVisGameMode + cine quality) ----
    go = config.find_or_add_setting_by_class(unreal.MoviePipelineGameOverrideSetting)
    go.cinematic_quality_settings = True
    go.use_high_quality_shadows = True
    # Leave SoftGameModeOverride at its default (MoviePipelineGameMode); the
    # ColliderVisMain map's own GameMode/PPV still applies. To force the project
    # GameMode set go.game_mode_override to AColliderVisGameMode if needed.

    # ---- Console variables (force Lumen offline quality) ----
    cvs = config.find_or_add_setting_by_class(unreal.MoviePipelineConsoleVariableSetting)
    # UE5.8: cvars are set via add_or_update_console_variable(name, value).
    nset = 0
    for k, v in CVARS.items():
        try:
            cvs.add_or_update_console_variable(k, float(v)); nset += 1
        except Exception as e:
            warn("[make_mrq_config] cvar {} failed: {}".format(k, e))
    log("[make_mrq_config] set {} console variables".format(nset))

    unreal.EditorAssetLibrary.save_asset(full_path)
    log("[make_mrq_config] Created MRQ config: {}".format(full_path))
    return full_path


def main():
    log("[make_mrq_config] Building MRQ assets for ColliderVis ...")
    seq_path = make_still_sequence()
    cfg_path = make_config()
    log("=" * 70)
    log("[make_mrq_config] DONE.")
    log("  Sequence : {}.{}".format(seq_path, SEQ_NAME))
    log("  Config   : {}.{}".format(cfg_path, CONFIG_NAME))
    log("  Render with: Tools/render_lumen_mrq.sh")
    log("=" * 70)


if __name__ == "__main__":
    main()
