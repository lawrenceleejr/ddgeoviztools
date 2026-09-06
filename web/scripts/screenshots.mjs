// screenshots.mjs — drive the built site through every chapter with Playwright
// and save one screenshot per chapter to shots/ for visual review.
//
//   npm run build && npm run preview &   # serves http://localhost:4173/ddgeoviztools/
//   node scripts/screenshots.mjs [--url http://localhost:4173/ddgeoviztools/] [--out shots]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const args = Object.fromEntries(process.argv.slice(2).map((a, i, arr) => (a.startsWith('--') ? [a.slice(2), arr[i + 1]] : [])).filter((x) => x.length));
// Default query: ?still (no idle spin, snapping spring) &fast (cheap shader for
// software GL) &lite (skip >100k-triangle systems). Pass --full 1 to keep the
// full geometry (≈ 11 s of SwiftShader GPU time per frame).
const url = (args.url ?? 'http://localhost:4173/ddgeoviztools/') + (args.query ?? (args.full ? '?still&fast' : '?still&fast&lite'));
const out = args.out ?? 'shots';
mkdirSync(out, { recursive: true });

const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: Number(args.w ?? 1440), height: Number(args.h ?? 900) }, deviceScaleFactor: 1 });
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') console.log(`[browser ${m.type()}]`, m.text()); });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));

const t0 = Date.now();
await page.goto(url, { waitUntil: 'networkidle' });
await page.waitForFunction(() => document.getElementById('loader')?.classList.contains('done'), null, { timeout: 120000 });
console.log(`loaded in ${((Date.now() - t0) / 1000).toFixed(1)}s`);
await page.waitForTimeout(1200); // loader fade-out

const sections = await page.$$eval('.chapter', (els) => els.map((e) => ({ id: e.id, top: e.getBoundingClientRect().top + scrollY, h: e.offsetHeight })));
for (const [k, s] of sections.entries()) {
  // Scroll 15% into the chapter's range (see ScrollEngine.read): scene held, copy active.
  const next = sections[k + 1];
  const end = next ? next.top : s.top + Math.max(1, s.h - Number(args.h ?? 900));
  const y = s.top + 0.15 * (end - s.top);
  await page.evaluate((yy) => scrollTo(0, Math.max(0, yy)), y);
  // Wait for the scroll spring to settle, then block on a 1-px readback so the
  // GPU has finished every queued frame before we capture.
  await page.waitForFunction(() => { const e = window.__maia?.engine; return e && e.value === e.target; }, null, { timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(300);
  const stats = await page.evaluate(() => {
    const gl = window.__maia.scene.renderer.getContext();
    const t = performance.now();
    gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4));
    return { gpuMs: Math.round(performance.now() - t), frames: window.__maia.frames, frameMs: window.__maia.frameMs };
  });
  const file = `${out}/${String(k).padStart(2, '0')}-${s.id}.png`;
  await page.screenshot({ path: file, timeout: 180000, animations: 'disabled' });
  process.stdout.write(`[${k + 1}/${sections.length}] ${file}  frames=${stats.frames} gpu wait=${stats.gpuMs} ms\n`);
}
await browser.close();

