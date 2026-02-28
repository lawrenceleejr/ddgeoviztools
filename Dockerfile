# ddgeoviztools — headless GDML splitter, mesh converter, and Blender scene builder
#
# Uses pyg4ometry (VTK) for GDML reading and OBJ/GLTF export.
# Uses bpy (Blender 4.0 Python module) for .blend scene creation.
# Mesa software-rendering drivers allow both VTK and bpy to run offscreen
# with no GPU and no display required.
#
# Build:  docker build -t ddgeoviztools .
# Run:    docker run --rm -v $(pwd):/data ddgeoviztools <subcommand> [args]

FROM python:3.10-slim

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
        libgl1-mesa-glx \
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
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Application source
# ---------------------------------------------------------------------------
COPY src/ ./src/

# Default working directory is /data — users volume-mount their files here
WORKDIR /data

# xvfb-run starts a throwaway virtual X server so VTK's render window works
# in containers that lack EGL / GPU drivers.  The -a flag picks a free display
# number automatically.  The window is never shown to the user.
ENTRYPOINT ["xvfb-run", "-a", "--server-args=-screen 0 1x1x24", \
            "python", "/app/src/cli.py"]
CMD ["--help"]
