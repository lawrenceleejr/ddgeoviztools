import { Suspense } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, Loader, AdaptiveDpr } from '@react-three/drei'
import * as THREE from 'three'
import { Detector } from './scene/Detector'
import { SceneEnvironment } from './scene/Environment'
import { Hud } from './ui/Hud'

export default function App() {
  return (
    <div className="app">
      <Canvas
        shadows
        dpr={[1, 2]}
        gl={{ antialias: true, powerPreference: 'high-performance' }}
        camera={{ position: [14, 9, 14], fov: 55, near: 0.1, far: 5000 }}
        onCreated={({ gl }) => {
          // Filmic look to match the Blender scene's AgX view transform.
          gl.toneMapping = THREE.AgXToneMapping
          gl.toneMappingExposure = 1.15
          // Enable per-material clipping for the phi cutaway (wired in a later step).
          gl.localClippingEnabled = true
        }}
      >
        <color attach="background" args={['#0c0f15']} />
        <fog attach="fog" args={['#0c0f15', 60, 220]} />

        <Suspense fallback={null}>
          <SceneEnvironment />
          <Detector />
        </Suspense>

        {/* Placeholder navigation — replaced by the third-person controller next. */}
        <OrbitControls
          makeDefault
          target={[0, 3, 0]}
          minDistance={2}
          maxDistance={120}
          maxPolarAngle={Math.PI / 1.9}
          enableDamping
        />
        <AdaptiveDpr pixelated />
      </Canvas>

      <Loader />
      <Hud />
    </div>
  )
}
