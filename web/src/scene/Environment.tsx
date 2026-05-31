import { Environment, Lightformer, ContactShadows } from '@react-three/drei'

/**
 * Even, soft "studio" lighting for the matte clay look: a strong hemisphere fill
 * keeps every surface bright and readable, a gentle key adds soft form + soft
 * shadows, and a neutral Lightformer environment supplies subtle image-based
 * fill. Baked Cycles AO (multiplied in via vertex colours) supplies the soft
 * ray-traced contact shadows on top.
 */
export function SceneEnvironment() {
  return (
    <>
      <hemisphereLight args={['#e8eeff', '#2a2d33', 0.85]} />
      <directionalLight
        position={[16, 26, 12]}
        intensity={0.6}
        color="#fff6ec"
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-near={1}
        shadow-camera-far={90}
        shadow-camera-left={-32}
        shadow-camera-right={32}
        shadow-camera-top={32}
        shadow-camera-bottom={-32}
        shadow-bias={-0.0002}
      />
      <ambientLight intensity={0.18} />

      <Environment resolution={256} frames={1} background={false}>
        <Lightformer form="rect" intensity={1.6} color="#eef2ff" scale={[30, 30, 1]} position={[0, 20, 0]} rotation={[Math.PI / 2, 0, 0]} />
        <Lightformer form="rect" intensity={1.0} color="#fff1df" scale={[16, 16, 1]} position={[-18, 8, 10]} rotation={[0, Math.PI / 2.4, 0]} />
        <Lightformer form="rect" intensity={0.9} color="#dfe9ff" scale={[16, 16, 1]} position={[18, 7, -8]} rotation={[0, -Math.PI / 2.4, 0]} />
        <Lightformer form="ring" intensity={1.2} color="#ffffff" scale={[8, 8, 1]} position={[0, 10, -22]} rotation={[0, Math.PI, 0]} />
      </Environment>

      <ContactShadows
        position={[0, 0.005, 0]}
        scale={80}
        resolution={1024}
        blur={2.8}
        far={32}
        opacity={0.5}
        color="#05070b"
      />
    </>
  )
}
