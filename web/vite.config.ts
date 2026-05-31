import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// `base` must match the GitHub Pages project path (https://<user>.github.io/ddgeoviztools/).
// It applies to dev, preview and build so import.meta.env.BASE_URL is consistent everywhere.
export default defineConfig({
  base: '/ddgeoviztools/',
  plugins: [react()],
  build: {
    target: 'es2020',
    chunkSizeWarningLimit: 2500,
  },
})
