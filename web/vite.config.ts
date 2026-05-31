import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'

// `base` must match the GitHub Pages project path (https://<user>.github.io/ddgeoviztools/).
// It applies to dev, preview and build so import.meta.env.BASE_URL is consistent everywhere.
//
// __BAKED__ is true when the Cycles bake has produced baked assets (CI runs the
// bake before the web build). When false the app falls back to the raw GLTFs, so
// `npm run dev` works with no Blender involved.
const bakedManifest = fileURLToPath(new URL('./public/baked/manifest.json', import.meta.url))
const hasBaked = fs.existsSync(bakedManifest)

export default defineConfig({
  base: '/ddgeoviztools/',
  plugins: [react()],
  define: {
    __BAKED__: JSON.stringify(hasBaked),
  },
  build: {
    target: 'es2020',
    chunkSizeWarningLimit: 2500,
  },
})
