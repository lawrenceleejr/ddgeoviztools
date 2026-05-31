import { test, expect } from '@playwright/test'

test('detector scene initialises under software WebGL', async ({ page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', (e) => pageErrors.push(String(e)))
  const consoleErrors: string[] = []
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text())
  })

  await page.goto('/ddgeoviztools/')

  // The app sets this once all sub-detectors have loaded and been placed.
  await page.waitForFunction(() => (window as any).__SCENE_READY__ === true, undefined, {
    timeout: 90_000,
  })

  const meshCount = await page.evaluate(() => (window as any).__MESH_COUNT__ ?? 0)
  expect(meshCount, 'detector meshes loaded').toBeGreaterThan(0)

  const canvas = page.locator('canvas')
  await expect(canvas).toBeVisible()
  const box = await canvas.boundingBox()
  expect(box?.width ?? 0, 'canvas has width').toBeGreaterThan(0)

  // Uncaught exceptions are always fatal; SwiftShader perf warnings are not.
  if (consoleErrors.length) {
    console.log('console.error during smoke:\n' + consoleErrors.join('\n'))
  }
  expect(pageErrors, pageErrors.join('\n')).toHaveLength(0)
})
