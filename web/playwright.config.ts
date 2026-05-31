import { defineConfig, devices } from '@playwright/test'

// Headless smoke test runs Chromium with SwiftShader (software WebGL) so it works
// in CI / this GPU-less environment. It validates that the scene boots and loads
// geometry — not visual quality, which must be checked on a real GPU.
export default defineConfig({
  testDir: './tests',
  timeout: 120_000,
  fullyParallel: false,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:4173',
    headless: true,
  },
  projects: [
    {
      name: 'chromium-swiftshader',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: {
          args: [
            '--use-gl=angle',
            '--use-angle=swiftshader',
            '--enable-unsafe-swiftshader',
            '--ignore-gpu-blocklist',
          ],
        },
      },
    },
  ],
  webServer: {
    command: 'npm run preview',
    port: 4173,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
