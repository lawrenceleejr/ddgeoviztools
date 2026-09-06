// screenshots.mjs — drive the built site through every chapter with Playwright
// and save one screenshot per chapter to shots/ for visual review.
//
//   npm run build && npm run preview &   # serves http://localhost:4173/ddgeoviztools/
//   node scripts/screenshots.mjs [--url http://localhost:4173/ddgeoviztools/] [--out shots]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const args = Object.fromEntries(process.argv.slice(2).map((a, i, arr) => (a.startsWith('--') ? [a.slice(2), arr[i + 1]] : [])).filter((x) => x.length));
const url = args.url ?? 'http://localhost:4173/ddgeoviztools/';
const out = args.out ?? 'shots';
mkdirSync(out, { recursive: true });

const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') console.log(`[browser ${m.type()}]`, m.text()); });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));

const t0 = Date.now();
await page.goto(url, { waitUntil: 'networkidle' });
await page.waitForFunction(() => document.getElementById('loader')?.classList.contains('done'), null, { timeout: 120000 });
console.log(`loaded in ${((Date.now() - t0) / 1000).toFixed(1)}s`);

const sections = await page.$$eval('.chapter', (els) => els.map((e) => ({ id: e.id, top: e.getBoundingClientRect().top + scrollY, h: e.offsetHeight })));
for (const [k, s] of sections.entries()) {
  // Scroll so the section's centre is 40% into its travel (copy active, scene held).
  const y = s.top + s.h * 0.15 - innerHeightOf(900) * 0.5 + 0;
  await page.evaluate((yy) => scrollTo(0, Math.max(0, yy)), y);
  await page.waitForTimeout(1600); // let the spring settle
  const file = `${out}/${String(k).padStart(2, '0')}-${s.id}.png`;
  await page.screenshot({ path: file });
  process.stdout.write(`[${k + 1}/${sections.length}] ${file}\n`);
}
await browser.close();

function innerHeightOf(h) { return h; }
