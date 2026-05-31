import { Suspense } from 'react'
import { Canvas } from '@react-three/fiber'
import { Loader, AdaptiveDpr, Grid } from '@react-three/drei'
import * as THREE from 'three'
import { Detector } from './scene/Detector'
import { BakedDetector } from './scene/BakedDetector'
import { SceneEnvironment } from './scene/Environment'
import { Player } from './player/Player'
import { Hud } from './ui/Hud'
import { useViewer } from './state/store'

export default function App() {
  const engaged = useViewer((s) => s.lookEngaged)

  return (
    <div className="app">
      <Canvas
        shadows
        dpr={[1, 2]}
        gl={{ antialias: true, powerPreference: 'high-performance' }}
        camera={{ position: [0, 2, 22], fov: 60, near: 0.1, far: 5000 }}
        onCreated={({ gl }) => {
          // Filmic look to match the Blender scene's AgX view transform.
          gl.toneMapping = THREE.AgXToneMapping
          gl.toneMappingExposure = 1.15
          // Enable per-material clipping for the phi cutaway (wired in a later step).
          gl.localClippingEnabled = true
        }}
      >
        <color attach="background" args={['#0c0f15']} />
        <fog attach="fog" args={['#0c0f15', 70, 260]} />

        <Suspense fallback={null}>
          <SceneEnvironment />
          {__BAKED__ ? <BakedDetector /> : <Detector />}
        </Suspense>

        <Grid
          args={[600, 600]}
          cellSize={1}
          cellThickness={0.5}
          cellColor="#1b2740"
          sectionSize={10}
          sectionThickness={1.1}
          sectionColor="#2a4d80"
          fadeDistance={140}
          fadeStrength={1.5}
          followCamera={false}
          infiniteGrid
          position={[0, 0, 0]}
        />

        <Player />
        <AdaptiveDpr pixelated />
      </Canvas>

      <Loader />
      {!engaged && (
        <div className="lookhint">
          <div className="lookhint-title">click to look around</div>
          <div className="lookhint-keys">
            <kbd>WASD</kbd> move · <kbd>Shift</kbd> run · <kbd>Space</kbd> jump ·{' '}
            <kbd>F</kbd> fly · scroll zoom · <kbd>Esc</kbd> release
          </div>
        </div>
      )}
      <Hud />
    </div>
  )
}
