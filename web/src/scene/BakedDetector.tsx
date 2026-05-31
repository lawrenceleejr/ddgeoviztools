import { useEffect, useLayoutEffect, useMemo, useRef } from 'react'
import { useGLTF } from '@react-three/drei'
import * as THREE from 'three'
import { MANIFEST } from './manifest'
import { fitToGround, signalReady } from './fit'
import { useViewer } from '../state/store'

// Single GLB produced by scripts/bake_lightmaps.py: the detector with Cycles
// lighting baked into per-object emissive textures (so it reads as the Blender
// render without any runtime lights). Built into web/public/baked/ by CI.
export const bakedUrl = `${import.meta.env.BASE_URL}baked/detector_baked.glb`
// The baked GLB is Draco-compressed; use the decoder shipped in public/draco/
// (no CDN dependency — works offline and on Pages).
const dracoPath = `${import.meta.env.BASE_URL}draco/`

if (typeof __BAKED__ !== 'undefined' && __BAKED__) {
  useGLTF.preload(bakedUrl, dracoPath)
}

/** Match a loaded node to a manifest sub-detector by name prefix/inclusion. */
function matchSubdetector(name: string): string | undefined {
  const n = name.toLowerCase()
  return MANIFEST.find((e) => n.includes(e.name.toLowerCase()))?.name
}

export function BakedDetector() {
  const { scene } = useGLTF(bakedUrl, dracoPath)
  const group = useRef<THREE.Group>(null)
  const visibility = useViewer((s) => s.visibility)

  const object = useMemo(() => {
    const clone = scene.clone(true)
    clone.traverse((o) => {
      const mesh = o as THREE.Mesh
      if (!mesh.isMesh) return
      mesh.castShadow = true
      mesh.receiveShadow = true
      mesh.userData.subdetector = matchSubdetector(mesh.name) ?? matchSubdetector(mesh.parent?.name ?? '')
      // The GLB carries the palette PBR materials + baked AO (COLOR_0, auto-multiplied
      // by three.js). Boost env reflections so the metal reads under the HDRI.
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
      for (const m of mats) {
        const std = m as THREE.MeshStandardMaterial
        if ('envMapIntensity' in std) std.envMapIntensity = 1.25
      }
    })
    return clone
  }, [scene])

  useLayoutEffect(() => {
    const g = group.current
    if (!g) return
    const { meshes, size } = fitToGround(g)
    signalReady(meshes)
    // eslint-disable-next-line no-console
    console.info(
      `[detector] ${meshes} meshes (baked), size ${size.x.toFixed(0)}×${size.y.toFixed(0)}×${size.z.toFixed(0)} mm`,
    )
  }, [])

  // Per-sub-detector visibility, matched by node name.
  useEffect(() => {
    const g = group.current
    if (!g) return
    g.traverse((o) => {
      const sd = o.userData?.subdetector as string | undefined
      if (sd) o.visible = visibility[sd] ?? true
    })
  }, [visibility])

  return (
    <group ref={group}>
      <primitive object={object} />
    </group>
  )
}
