/// <reference types="vite/client" />

// Globals the app sets once the detector has loaded — used by the Playwright
// smoke test to assert the scene initialised without a GPU-dependent visual check.
interface Window {
  __SCENE_READY__?: boolean
  __MESH_COUNT__?: number
}
