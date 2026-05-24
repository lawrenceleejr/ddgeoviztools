# ddgeoviztools — headless GDML splitter, mesh converter, and Blender scene builder
#
# Uses pyg4ometry (VTK) for GDML reading and OBJ/GLTF export.
# Uses bpy (Blender 4.0 Python module) for .blend scene creation.
# Mesa software-rendering drivers allow both VTK and bpy to run offscreen
# with no GPU and no display required.
#
# Build:  docker build -t ddgeoviztools .
# Run:    docker run --rm -v $(pwd):/data ddgeoviztools <subcommand> [args]

#FROM python:3.10-slim
FROM linuxserver/blender:5.0.1


# ---------------------------------------------------------------------------
# System libraries
#   libgl1 / libglu1-mesa        — OpenGL (Mesa software implementation)
#   libegl1 / libegl-mesa0       — EGL (headless OpenGL context creation)
#   libgles2                     — OpenGL ES 2 (required by some VTK paths)
#   libgomp1                     — OpenMP (used by VTK for parallel rendering)
#   libxrender1 libice6 libsm6   — X11 client libraries used by VTK internals
#   libxt6 libx11-6 libxext6     — additional X11 / bpy deps
#   libfreetype6 libfontconfig1  — font rendering used by bpy in background mode
#   xvfb                         — virtual X framebuffer (fallback if EGL fails)
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglu1-mesa \
        libegl1 \
        libegl-mesa0 \
        libgles2 \
        libgomp1 \
        libxrender1 \
        libice6 \
        libsm6 \
        libxt6 \
        libx11-6 \
        libxext6 \
        libfreetype6 \
        libfontconfig1 \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Python dependencies
# ---------------------------------------------------------------------------
WORKDIR /app
COPY requirements.txt .

# Install into the *system* Python used by the ENTRYPOINT (pyg4ometry, vtk, …)
RUN pip install --no-cache-dir -r requirements.txt

# Install into Blender's *bundled* Python, which is a separate interpreter.
# gdml_to_blender.py is executed via "blender --background --python …" and
# therefore runs in Blender's own Python (which has bpy/mathutils but not
# third-party packages).  We use blender --python-expr to reach its pip.
RUN blender --background --python-expr \
        "import subprocess, sys; subprocess.check_call([sys.executable, '-m', 'ensurepip'])" \
 && blender --background --python-expr \
        "import subprocess, sys; subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', 'trimesh'])"

# ---------------------------------------------------------------------------
# Application source
# ---------------------------------------------------------------------------
COPY src/ ./src/

# Default working directory is /data — users volume-mount their files here
WORKDIR /data

# Force Mesa software rendering so VTK works headless without a GPU or X server.
# PYOPENGL_PLATFORM=egl uses EGL (no display connection required).
# LIBGL_ALWAYS_SOFTWARE=1 forces Mesa's CPU rasteriser even if a GPU is present.
# These are only consulted by the convert/split-convert subcommands; split and
# blender-scene do not import VTK at all.
ENV PYOPENGL_PLATFORM=egl \
    LIBGL_ALWAYS_SOFTWARE=1 \
    GALLIUM_DRIVER=llvmpipe

ENTRYPOINT ["python", "/app/src/cli.py"]
CMD ["--help"]
