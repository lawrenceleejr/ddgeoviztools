# render_glamour.py — easy super-high-quality still renders of the ColliderVis detector.
#
# HOW TO USE (in the Unreal Editor, with the editor window FOCUSED so it renders):
#   Window ▸ "Output Log" ▸ switch the bottom dropdown to "Cmd" → "Python", then:
#
#     import sys; sys.path.append(r"/Users/leejr/Work/ddgeoviztools/ColliderVis/Tools")
#     import render_glamour as g
#     g.shot()                       # one hero shot at the current best angle, 4K
#     g.shot(yaw=60, pitch=-18)      # custom orbit angle
#     g.turntable(count=16)          # 16 stills orbiting the detector (great for a contact sheet)
#     g.cinematic_quality()          # push r.* cvars to max before a final render
#
# Output PNGs land in:  ColliderVis/Saved/Screenshots/MacEditor/
# (HighResShot renders at full quality off the focused editor viewport — no PIE needed.)
#
# NOTE: rendering needs the editor to be the FOREGROUND app (it throttles in the background),
# so run these while you're looking at the editor. For unattended batch renders use Movie
# Render Queue (see RENDER_GUIDE.md).

import unreal, math

# Detector sits at the world origin; aim slightly above the interaction point.
CENTER = unreal.Vector(0.0, 0.0, 60.0)


def _orbit_location(yaw_deg, pitch_deg, distance):
    """Position on a sphere of `distance` around CENTER at the given yaw/pitch."""
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    horiz = distance * math.cos(pitch)
    x = CENTER.x + horiz * math.cos(yaw)
    y = CENTER.y + horiz * math.sin(yaw)
    z = CENTER.z - distance * math.sin(pitch)   # negative pitch = camera above, looking down
    return unreal.Vector(x, y, z)


def _look_at_rotation(cam_loc):
    d = unreal.Vector(CENTER.x - cam_loc.x, CENTER.y - cam_loc.y, CENTER.z - cam_loc.z)
    return d.rotator()


def cinematic_quality():
    """Crank scalability + Lumen for a final-quality render."""
    cmds = [
        "sg.PostProcessQuality 4", "sg.ShadowQuality 4", "sg.GlobalIlluminationQuality 4",
        "sg.ReflectionQuality 4", "sg.TextureQuality 4", "sg.EffectsQuality 4",
        "sg.ViewDistanceQuality 4", "sg.AntiAliasingQuality 4",
        "r.Lumen.Reflections.Quality 3", "r.Lumen.ScreenProbeGather.RadianceCache 1",
        "r.TemporalAA.Upsampling 1", "r.ScreenPercentage 100",
    ]
    for c in cmds:
        unreal.SystemLibrary.execute_console_command(unreal.EditorLevelLibrary.get_editor_world(), c)
    unreal.log("[render_glamour] cinematic quality cvars applied")


def shot(yaw=135.0, pitch=-14.0, distance=1300.0, res="3840x2160"):
    """Place the editor viewport camera on an orbit angle and take a HighResShot.

    yaw/pitch  — orbit angles in degrees (pitch negative = looking down).
    distance   — cm from the detector centre (stay < ~1750 to remain inside the hall).
    res        — "WIDTHxHEIGHT" (e.g. "3840x2160" 4K, "7680x4320" 8K) or a multiplier like "2".
    """
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    loc = _orbit_location(yaw, pitch, distance)
    rot = _look_at_rotation(loc)
    ues.set_level_viewport_camera_info(loc, rot)
    unreal.EditorLevelLibrary.editor_invalidate_viewports()
    w = unreal.EditorLevelLibrary.get_editor_world()
    unreal.SystemLibrary.execute_console_command(w, "HighResShot " + str(res))
    unreal.log("[render_glamour] HighResShot %s @ yaw=%.0f pitch=%.0f dist=%.0f" % (res, yaw, pitch, distance))


def turntable(count=12, pitch=-14.0, distance=1300.0, res="2560x1440"):
    """Render `count` stills evenly spaced around the detector (contact sheet / turntable)."""
    for i in range(count):
        shot(yaw=i * (360.0 / count), pitch=pitch, distance=distance, res=res)
    unreal.log("[render_glamour] turntable of %d shots queued" % count)


# ── Curated hero poses (found during the overnight polish pass) ───────────────
# Exact camera placements that frame the glowing cutaway well. Usage:
#   g.pose("hero")            # the primary tight 3/4 hero
#   g.pose("front")           # symmetric cutaway, beamline centered
#   g.pose("establishing")    # wider, higher — whole detector in the hall
#   g.pose("hero", res="7680x4320")   # 8K
HERO_POSES = {
    "hero":         (unreal.Vector(-720, -820, 300),  unreal.Rotator(-12.0, 49.0, 0.0), 28.0),
    "front":        (unreal.Vector(0,    -1300, 300), unreal.Rotator(-13.0, 90.0, 0.0), 35.0),
    "establishing": (unreal.Vector(-820, -920, 560), unreal.Rotator(-21.0, 48.0, 0.0), 24.0),
    "side":         (unreal.Vector(-1150,-150, 320), unreal.Rotator(-11.0, 7.0,  0.0), 35.0),
}

def pose(name="hero", res="3840x2160"):
    """Snap the editor viewport to a curated hero pose and take a HighResShot."""
    loc, rot, focal = HERO_POSES[name]
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    ues.set_level_viewport_camera_info(loc, rot)
    unreal.EditorLevelLibrary.editor_invalidate_viewports()
    w = unreal.EditorLevelLibrary.get_editor_world()
    unreal.SystemLibrary.execute_console_command(w, "HighResShot " + str(res))
    unreal.log("[render_glamour] pose '%s' @ %s -> HighResShot %s" % (name, loc, res))

def all_heroes(res="3840x2160"):
    """Render every curated hero pose (one PNG each)."""
    for n in HERO_POSES:
        pose(n, res=res)
