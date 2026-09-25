/* Render assets/og-card.svg to assets/og.png at exactly 1200x630 (P1-4).
 *
 * A link preview wants a raster image; SVG is not reliably fetched or
 * decoded by Telegram, Instagram or Facebook. The SVG stays in the
 * repository as the editable source and this turns it into the file the
 * meta tag points at.
 *
 *   node browser-tests/tools/render-og.js
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..', '..');
const SRC = path.join(ROOT, 'assets', 'og-card.svg');
const OUT = path.join(ROOT, 'assets', 'og.png');
const W = 1200, H = 630;

(async () => {
  const svg = fs.readFileSync(SRC, 'utf8');
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: W, height: H },
                                       deviceScaleFactor: 1 });
  await page.setContent(
    `<!doctype html><meta charset="utf-8">
     <style>html,body{margin:0;padding:0;background:#1a3fa0}svg{display:block}</style>
     ${svg}`, { waitUntil: 'load' });
  await page.screenshot({ path: OUT, clip: { x: 0, y: 0, width: W, height: H } });
  await browser.close();
  const { size } = fs.statSync(OUT);
  console.log(`wrote ${path.relative(ROOT, OUT)} — ${W}x${H}, ${(size / 1024).toFixed(0)} KB`);
})();
