import { Suspense } from 'react'
import { Canvas } from '@react-three/fiber'
import { Loader, AdaptiveDpr, Grid, SoftShadows } from '@react-three/drei'
import { EffectComposer, Bloom, ToneMapping, SMAA, Vignette } from '@react-three/postprocessing'
import { ToneMappingMode } from 'postprocessing'
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
        gl={{ antialias: false, powerPreference: 'high-performance' }}
        camera={{ position: [0, 2, 22], fov: 60, near: 0.1, far: 5000 }}
        onCreated={({ gl }) => {
          // Tone mapping is applied by the post-processing AgX pass below.
          gl.toneMapping = THREE.NoToneMapping
          // Per-material clipping for the phi cutaway (wired in a later step).
          gl.localClippingEnabled = true
        }}
      >
        <color attach="background" args={['#0c0f15']} />
        <fog attach="fog" args={['#0c0f15', 70, 260]} />

        {/* Softens all shadow-map edges for the ray-traced look. */}
        <SoftShadows size={28} samples={12} focus={0.7} />

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

        <EffectComposer multisampling={0} enableNormalPass={false}>
          <Bloom mipmapBlur luminanceThreshold={1.0} luminanceSmoothing={0.3} intensity={0.7} />
          <ToneMapping mode={ToneMappingMode.AGX} />
          <SMAA />
          <Vignette offset={0.25} darkness={0.55} eskil={false} />
        </EffectComposer>
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
