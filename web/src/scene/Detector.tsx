import { useLayoutEffect, useMemo, useRef } from 'react'
import { useGLTF } from '@react-three/drei'
import * as THREE from 'three'
import { MANIFEST, modelUrl, type SubDetector } from './manifest'
import { useViewer } from '../state/store'

// Preload every sub-detector so the whole assembly pops in together.
MANIFEST.forEach((m) => useGLTF.preload(modelUrl(m.file)))

function cloneMaterial(m: THREE.Material, envMapIntensity: number): THREE.Material {
  const c = m.clone() as THREE.MeshStandardMaterial
  if ('envMapIntensity' in c) c.envMapIntensity = envMapIntensity
  c.needsUpdate = true
  return c
}

function prepare(root: THREE.Object3D, part: SubDetector) {
  root.traverse((obj) => {
    const mesh = obj as THREE.Mesh
    if (!mesh.isMesh) return
    mesh.castShadow = true
    mesh.receiveShadow = true
    mesh.userData.subdetector = part.name
    // Clone materials so per-part tweaks don't leak into the shared useGLTF cache.
    if (Array.isArray(mesh.material)) {
      mesh.material = mesh.material.map((m) => cloneMaterial(m, part.envMapIntensity))
    } else if (mesh.material) {
      mesh.material = cloneMaterial(mesh.material, part.envMapIntensity)
    }
  })
}

function DetectorPart({ part }: { part: SubDetector }) {
  const { scene } = useGLTF(modelUrl(part.file))
  const visible = useViewer((s) => s.visibility[part.name] ?? true)
  const object = useMemo(() => {
    const clone = scene.clone(true)
    prepare(clone, part)
    return clone
  }, [scene, part])
  return <primitive object={object} visible={visible} />
}

/**
 * Loads all sub-detectors, then recentres + rescales the assembly once:
 * GDML units are millimetres, so we scale by 1e-3 into metres (good for a
 * human-scale avatar and physics), drop it onto the y=0 ground, and centre it
 * horizontally. The GDML frame is already Y-up / Z-beam (no rotation needed).
 */
export function Detector() {
  const group = useRef<THREE.Group>(null)

  useLayoutEffect(() => {
    const g = group.current
    if (!g) return
    // Reset first so the measurement is independent of any previous run
    // (React StrictMode invokes layout effects twice in dev).
    g.position.set(0, 0, 0)
    g.scale.setScalar(1)
    g.updateWorldMatrix(true, true)
    const box = new THREE.Box3().setFromObject(g)
    if (box.isEmpty()) return
    const size = box.getSize(new THREE.Vector3())
    const center = box.getCenter(new THREE.Vector3())
    const MM_TO_M = 0.001
    g.scale.setScalar(MM_TO_M)
    g.position.set(-center.x * MM_TO_M, -box.min.y * MM_TO_M, -center.z * MM_TO_M)

    let meshes = 0
    g.traverse((o) => {
      if ((o as THREE.Mesh).isMesh) meshes++
    })
    window.__MESH_COUNT__ = meshes
    window.__SCENE_READY__ = true
    // eslint-disable-next-line no-console
    console.info(
      `[detector] ${meshes} meshes, raw size ${size.x.toFixed(0)}×${size.y.toFixed(0)}×${size.z.toFixed(
        0,
      )} mm`,
    )
  }, [])

  return (
    <group ref={group}>
      {MANIFEST.map((part) => (
        <DetectorPart key={part.name} part={part} />
      ))}
    </group>
  )
}
