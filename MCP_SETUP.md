# Agentic Unreal control on your Mac (mcp-unreal)

This sets up [`remiphilippe/mcp-unreal`](https://github.com/remiphilippe/mcp-unreal) so Claude
Code can drive the ColliderVis editor directly — import geometry, build the level, compile,
take viewport screenshots, and iterate on lighting — over the Model Context Protocol.

It pairs with `ColliderVis/Tools/ue5_build_content.py` (the one-shot content builder): Claude
runs that script through the MCP `execute_script` tool, then uses `capture_viewport` to *see*
the result and refine.

---

## Prerequisites (macOS)

| Tool | Notes |
|------|-------|
| Unreal Engine **5.7** | Epic Games Launcher. Default path `/Users/Shared/Epic Games/UE_5.7` (matches `scripts/build_mac.sh` and the mcp-unreal default `UE_EDITOR_PATH`). |
| Xcode 26+ | Required to compile the C++ project + the MCPUnreal plugin. |
| Docker | For the Blender export step (`scripts/blend_to_ue5_export.sh`). |
| Claude Code | This repo ships a `.mcp.json` that registers the server. |
| Go 1.25+ | Only if you build `mcp-unreal` from source instead of using a release binary. |

---

## 1. Install the mcp-unreal server

Either download the macOS (arm64 or amd64) binary from the project's GitHub Releases, or build
from source:

```bash
git clone https://github.com/remiphilippe/mcp-unreal.git
cd mcp-unreal
make build
```

Put the binary on your `PATH` (or point `MCP_UNREAL_BIN` at it), then build its docs index:

```bash
sudo cp mcp-unreal /usr/local/bin/        # or: export MCP_UNREAL_BIN=/full/path/to/mcp-unreal
mcp-unreal --build-index                  # creates ./docs/index.bleve for lookup_docs
```

## 2. Install the MCPUnreal editor plugin

mcp-unreal ships a custom C++ plugin that exposes deep editor integration on port 8090. Copy it
into this project's `Plugins/` folder and let it rebuild with the project:

```bash
cp -r /path/to/mcp-unreal/plugin "$PWD/ColliderVis/Plugins/MCPUnreal"
```

> `ColliderVis/Plugins/` is git-ignored for vendored third-party plugins — keep the MCPUnreal
> source out of this repo's history; it lives with the engine tooling on your machine.

## 3. Enable the editor plugins

`ColliderVis.uproject` already enables **Remote Control**, **Python Editor Script Plugin**, and
**Editor Scripting Utilities**. When you first open the project, also enable **MCPUnreal**
(*Edit → Plugins → search "MCPUnreal" → Enabled → restart*). Verify Remote Control is live:

```bash
curl http://localhost:30010/remote/info     # should return JSON once the editor is open
```

## 4. Register the server with Claude Code

The repo's `.mcp.json` already declares the server. Before launching Claude Code from the repo
root, export the project path (and the binary location if it isn't on `PATH`):

```bash
export MCP_UNREAL_PROJECT="$PWD/ColliderVis/ColliderVis.uproject"
# export MCP_UNREAL_BIN=/full/path/to/mcp-unreal   # only if not on PATH
```

Or register it explicitly instead of relying on `.mcp.json`:

```bash
claude mcp add mcp-unreal -- mcp-unreal
```

Other env vars (defaults shown): `RC_API_PORT=30010`, `PLUGIN_PORT=8090`,
`UE_EDITOR_PATH=/Users/Shared/Epic Games/UE_5.7/Engine/Binaries/Mac/UnrealEditor-Cmd`.

---

## 5. Drive it (end-to-end)

With the UE editor open on `ColliderVis.uproject` and Claude Code running from the repo root:

```bash
# 1. (terminal) Blender .blend -> UE-ready GLTF + manifest (meshes + lights + cameras)
scripts/blend_to_ue5_export.sh /path/to/detector.blend -o /tmp/ue5_meshes
```

Then ask Claude (it will use the mcp-unreal tools):

1. `status` — confirm the editor is connected.
2. `execute_script` — run the content builder:
   ```python
   import sys; sys.path.append(r"<repo>/ColliderVis/Tools")
   import ue5_build_content as b
   b.build({"manifest_dir": "/tmp/ue5_meshes"})
   ```
   Watch stdout for the `COLLIDERVIS_BUILD_RESULT={...}` summary (and any `MANUAL TODO` lines).
3. `build_project` — compile the C++ (incl. the GameMode/character changes + MCPUnreal plugin).
4. `capture_viewport` — screenshot `ColliderVisMain`: confirm the detector renders with the
   **cutaway** open, lit by the **imported Blender rig** (not the old clean-room look). If the
   lights look mirrored, flip `FLIP_Y` at the top of `ue5_build_content.py` and re-run stage 7.
5. Iterate on light intensity (`LUMENS_PER_WATT` / `LUX_PER_WM2`) until the screenshot matches
   your Blender render — this is the intended convergence loop.

### Useful mcp-unreal tools for this project
`execute_script` (run our Python), `build_project` / `run_tests`, `capture_viewport`,
`pie_control` + `player_control` (walk the third-person character, hold RMB to zoom),
`get_level_actors` / `spawn_actor` / `set_property`, `material_ops`, `input_ops`,
`lookup_docs` / `lookup_class` (UE 5.7 API).

---

## Manual TODOs the builder reports (finish in-editor / via MCP)

- **Example character model:** add the **Third Person** feature pack (*Content Browser → Add →
  Add Feature or Content Pack → Third Person*) so `/Game/Characters/Mannequins/*` exists; the
  character auto-binds `SKM_Quinn_Simple` + `ABP_Quinn` on the next compile.
- **WBP_Options / WBP_DetectorRow:** the builder creates the widget *assets*; build their visual
  layout + button wiring in the UMG designer per `UE5_SETUP.md` §7.
- **IMC_VR:** desktop input is fully built; some XR controller bindings may need finishing by
  hand depending on your installed VR plugins (`UE5_SETUP.md` §3c).
