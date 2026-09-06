import { defineConfig } from 'vite';

// Served from https://lawrenceleejr.github.io/ddgeoviztools/ — a project page,
// hence the sub-path base. Override with VITE_BASE=/ for a user/root site.
export default defineConfig({
  base: process.env.VITE_BASE ?? '/ddgeoviztools/',
  build: {
    target: 'es2022',
    sourcemap: false,
    assetsInlineLimit: 0,
  },
  server: { port: 5173, strictPort: true },
});
