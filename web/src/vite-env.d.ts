/// <reference types="vite/client" />

// Build-time flag injected by vite.config.ts: true when a Cycles bake is present.
declare const __BAKED__: boolean

// Globals the app sets once the detector has loaded — used by the Playwright
// smoke test to assert the scene initialised without a GPU-dependent visual check.
interface Window {
  __SCENE_READY__?: boolean
  __MESH_COUNT__?: number
}
