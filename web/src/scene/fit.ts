import * as THREE from 'three'

/**
 * Recentre + rescale an assembly once: GDML/Blender units are millimetres, so
 * scale into metres, sit the object on the y=0 ground, and centre it
 * horizontally. Idempotent (safe under React StrictMode double-invoke).
 */
export function fitToGround(group: THREE.Object3D, mmToM = 0.001) {
  group.position.set(0, 0, 0)
  group.scale.setScalar(1)
  group.updateWorldMatrix(true, true)

  const box = new THREE.Box3().setFromObject(group)
  if (box.isEmpty()) return { meshes: 0, size: new THREE.Vector3() }

  const center = box.getCenter(new THREE.Vector3())
  const size = box.getSize(new THREE.Vector3())
  group.scale.setScalar(mmToM)
  group.position.set(-center.x * mmToM, -box.min.y * mmToM, -center.z * mmToM)

  let meshes = 0
  group.traverse((o) => {
    if ((o as THREE.Mesh).isMesh) meshes++
  })
  return { meshes, size }
}

/** Signal the smoke test (and any health check) that the scene is up. */
export function signalReady(meshes: number) {
  window.__MESH_COUNT__ = meshes
  window.__SCENE_READY__ = true
}
