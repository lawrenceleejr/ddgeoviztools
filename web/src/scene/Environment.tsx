import { Environment, Lightformer, ContactShadows } from '@react-three/drei'

/**
 * Real-time lighting layer (plan layer 2): a procedural studio HDRI built from
 * Lightformers — no external .hdr asset to ship, fully offline — gives the metal
 * sub-detectors view-dependent reflections + specular. A soft directional key adds
 * shaping, and ContactShadows grounds the assembly. Baked Cycles lightmaps (layer 1)
 * are layered on top later via the bake pipeline.
 */
export function SceneEnvironment() {
  return (
    <>
      <hemisphereLight args={['#afc6ff', '#20242c', 0.35]} />
      <directionalLight
        position={[14, 22, 10]}
        intensity={1.6}
        color="#fff4e6"
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-near={1}
        shadow-camera-far={80}
        shadow-camera-left={-30}
        shadow-camera-right={30}
        shadow-camera-top={30}
        shadow-camera-bottom={-30}
        shadow-bias={-0.0002}
      />

      <Environment resolution={256} frames={1} background={false}>
        {/* Big soft skylight overhead — the dominant reflection on horizontal metal. */}
        <Lightformer
          form="rect"
          intensity={3}
          color="#eaf2ff"
          scale={[24, 24, 1]}
          position={[0, 18, 0]}
          rotation={[Math.PI / 2, 0, 0]}
        />
        {/* Warm key from camera-left. */}
        <Lightformer form="rect" intensity={2.2} color="#ffe9cf" scale={[12, 12, 1]} position={[-16, 8, 8]} rotation={[0, Math.PI / 2.4, 0]} />
        {/* Cool fill from camera-right. */}
        <Lightformer form="rect" intensity={1.4} color="#cfe2ff" scale={[12, 12, 1]} position={[16, 6, -6]} rotation={[0, -Math.PI / 2.4, 0]} />
        {/* Bright rim behind to pop silhouettes. */}
        <Lightformer form="ring" intensity={2.6} color="#ffffff" scale={[6, 6, 1]} position={[0, 9, -20]} rotation={[0, Math.PI, 0]} />
        {/* Subtle warm bounce from the floor. */}
        <Lightformer form="rect" intensity={0.6} color="#3a3330" scale={[30, 30, 1]} position={[0, -2, 0]} rotation={[-Math.PI / 2, 0, 0]} />
      </Environment>

      <ContactShadows
        position={[0, 0.005, 0]}
        scale={70}
        resolution={1024}
        blur={2.6}
        far={30}
        opacity={0.55}
        color="#05070b"
      />
    </>
  )
}
