/* A93/A94: an iPhone photo has to survive the whole flow, not just the tray.
 *
 * HEIC uploads, a layout change, a preview that actually renders, and a
 * checkout that is reachable. The bug: ingest wrote JPEG copies so the tray
 * looked perfect, while preview and print read the ORIGINAL — still HEIC —
 * in a worker that had never registered the HEIF opener.
 *
 * THIS CHECK DOES NOT GUARD THAT BUG, and it is worth being exact about why.
 * The dev server runs with TASK_EAGER, so ingest, preview and render all
 * happen inside the API process — which imports the photos service and so
 * registers the opener no matter where the registration lives. Measured: with
 * the original fault restored (registered in `image_processing` alone), this
 * check passes end to end. Only production forks, and only a forked preview
 * child misses it.
 *
 * What guards it is `backend/tests/render/test_heic_pipeline.py`, which runs
 * the render path in a SUBPROCESS that imports nothing else. This file is
 * here for the other half: that a real HEIC survives upload, layout changes,
 * preview and the road to checkout.
 *
 *   node checks/heicflow.js
 */
const { chromium } = require('playwright');
const path = require('path');
const BASE = 'http://127.0.0.1:8000';
const SHOTS = path.join(__dirname, '..', 'shots');
const HEIC = Array.from({ length: 4 }, (_, i) =>
  path.join(__dirname, '..', 'fixtures', `iphone${i}.heic`));

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

(async () => {
  require('fs').mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e)));

  await page.goto(`${BASE}/editor/`);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/editor/`);
  await page.click('.btype[data-btype="memory"]');
  await page.waitForFunction(() => document.querySelector('[data-tier-pages]').textContent,
    undefined, { timeout: 30000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');

  console.log('HEIC UPLOADS');
  await page.setInputFiles('#file-input', HEIC);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('4 '),
    undefined, { timeout: 180000 });
  const failedCards = await page.$$eval('.ph-card.failed', (els) => els.length);
  check('all four ingest without failing', failedCards === 0, `${failedCards} failed`);

  console.log('PLACED ACROSS DIFFERENT LAYOUTS');
  // page 1 gets a grid, page 2 a single — the mix the report described
  await page.click('#filmstrip .film-item:nth-child(2)');
  await page.waitForFunction(
    () => document.getElementById('page-canvas').classList.contains('page-mode'),
    undefined, { timeout: 10000 });
  await page.click('#btn-layout');
  await page.waitForSelector('.layout-pop', { timeout: 10000 });
  await page.click('.layout-pop .lay-item:nth-child(6)');   // four-up
  await page.waitForTimeout(400);
  for (let i = 0; i < 4; i += 1) {
    await page.click(`.tray-grid .ph-card:nth-child(${i + 1})`);
    await page.waitForTimeout(250);
  }
  await page.click('#btn-autofill');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 60000 });
  check('a book of HEIC photos saves', true);

  console.log('THE PREVIEW ACTUALLY RENDERS');
  await page.click('#btn-preview');
  await page.waitForSelector('#screen-preview.active', { timeout: 30000 });
  // Either it renders, or it says it failed — wait for whichever comes.
  await page.waitForFunction(() => {
    const figs = document.querySelectorAll('#pv-grid figure').length;
    const status = document.getElementById('pv-status').textContent.trim();
    return figs > 0 || (status && !document.getElementById('pv-status')
      .classList.contains('busy'));
  }, undefined, { timeout: 240000 });
  const figs = await page.$$eval('#pv-grid figure', (els) => els.length);
  const status = await page.$eval('#pv-status', (el) => el.textContent.trim());
  check('the preview renders pages rather than failing', figs > 0,
    `${figs} tiles, status ${JSON.stringify(status)}`);
  await page.screenshot({ path: `${SHOTS}/93-heic-preview.png` });

  console.log('AND CHECKOUT IS REACHABLE (A94)');
  const staleShown = await page.evaluate(
    () => !document.getElementById('pv-stale').classList.contains('hidden'));
  check('no "layout changed" banner on a freshly built preview', !staleShown);
  await page.check('#pv-confirm');
  await page.waitForSelector('#pv-checkout:not([disabled])', { timeout: 30000 });
  check('the order button is enabled', true);

  console.log('errors:', errs.length ? errs : 'none');
  await browser.close();
  if (errs.length || failed) {
    console.error(`HEIC FLOW CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('HEIC FLOW CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
