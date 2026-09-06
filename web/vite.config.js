import { resolve } from 'node:path';
import { defineConfig } from 'vite';

// Served from https://lawrenceleejr.github.io/ddgeoviztools/ — a project page,
// hence the sub-path base. Override with VITE_BASE=/ for a user/root site.
export default defineConfig({
  base: process.env.VITE_BASE ?? '/ddgeoviztools/',
  build: {
    // GitHub Pages serves this branch's /docs folder as-is, so the build
    // output is committed there rather than left in web/dist.
    outDir: resolve(import.meta.dirname, '../docs'),
    emptyOutDir: true,
    target: 'es2022',
    sourcemap: false,
    assetsInlineLimit: 0,
  },
  server: { port: 5173, strictPort: true },
});
