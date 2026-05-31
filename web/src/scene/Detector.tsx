import { useLayoutEffect, useMemo, useRef } from 'react'
import { useGLTF } from '@react-three/drei'
import * as THREE from 'three'
import { MANIFEST, modelUrl, type SubDetector } from './manifest'
import { fitToGround, signalReady } from './fit'
import { useViewer } from '../state/store'

// Preload every sub-detector so the whole assembly pops in together.
MANIFEST.forEach((m) => useGLTF.preload(modelUrl(m.file)))

function prepare(root: THREE.Object3D, part: SubDetector) {
  // Soft matte "clay" material per sub-detector (no bake here — the raw dev path).
  const mat = new THREE.MeshStandardMaterial({
    color: new THREE.Color(part.clay),
    metalness: 0.0,
    roughness: 0.9,
    envMapIntensity: 0.35,
  })
  root.traverse((obj) => {
    const mesh = obj as THREE.Mesh
    if (!mesh.isMesh) return
    mesh.castShadow = true
    mesh.receiveShadow = true
    mesh.userData.subdetector = part.name
    mesh.material = mat
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
    const { meshes, size } = fitToGround(g)
    signalReady(meshes)
    // eslint-disable-next-line no-console
    console.info(
      `[detector] ${meshes} meshes (raw), size ${size.x.toFixed(0)}×${size.y.toFixed(0)}×${size.z.toFixed(0)} mm`,
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
