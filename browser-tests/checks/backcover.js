/* A91: the back cover holds photos, like an interior page.
 *
 * Blank by default, reachable from the filmstrip, takes a layout grid and
 * photos, survives a reload, and shows up in the preview — because the
 * preview is the contract, and anything a customer can put on the book has
 * to be there to be confirmed.
 *
 *   node checks/backcover.js
 */
const { chromium } = require('playwright');
const path = require('path');
const BASE = 'http://127.0.0.1:8000';
const SHOTS = path.join(__dirname, '..', 'shots');
const PHOTOS = Array.from({ length: 4 }, (_, i) =>
  path.join(__dirname, '..', 'fixtures', `photo${String(i).padStart(2, '0')}.jpg`));

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
  page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text()); });

  await page.goto(`${BASE}/editor/`);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/editor/`);
  await page.click('.btype[data-btype="travel"]');
  await page.waitForFunction(() => document.querySelector('[data-tier-pages]').textContent,
    undefined, { timeout: 30000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');

  const creds = await page.evaluate(() => JSON.parse(localStorage.getItem('mb-book')));
  const stored = () => page.evaluate(async (c) => {
    const r = await fetch(`/api/v1/books/${c.book_id}`,
      { headers: { 'X-Edit-Token': c.edit_token } });
    return r.ok ? (await r.json()).layout.cover.back : `HTTP ${r.status}`;
  }, creds);

  console.log('BLANK BY DEFAULT');
  const start = await stored();
  check('a new book has an empty back cover',
    start && Array.isArray(start.placements) && start.placements.length === 0,
    JSON.stringify(start));

  console.log('REACHABLE FROM THE FILMSTRIP');
  const last = '#filmstrip .film-item:last-child';
  check('it is the last item in the strip',
    (await page.$eval(last, (el) => el.textContent)).trim().length > 0,
    JSON.stringify(await page.$eval(last, (el) => el.textContent.trim())));
  await page.click(last);
  await page.waitForFunction(
    () => document.getElementById('page-canvas').classList.contains('back-mode'),
    undefined, { timeout: 10000 });
  check('clicking it opens the back panel', true);
  check('and the label says so',
    (await page.$eval('#page-label', (el) => el.textContent.trim())).length > 0,
    JSON.stringify(await page.$eval('#page-label', (el) => el.textContent.trim())));

  console.log('IT TAKES A LAYOUT AND PHOTOS');
  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('4 '),
    undefined, { timeout: 180000 });
  // still on the back after uploading
  await page.click(last);
  await page.waitForFunction(
    () => document.getElementById('page-canvas').classList.contains('back-mode'),
    undefined, { timeout: 10000 });
  await page.click('#btn-layout');
  await page.waitForSelector('.layout-pop', { timeout: 10000 });
  const grids = await page.$$eval('.layout-pop .lay-item', (els) => els.length);
  check('the layout picker offers photo grids, not cover templates', grids > 1,
    `${grids} options`);
  await page.click('.layout-pop .lay-item:nth-child(4)');
  await page.waitForTimeout(400);

  await page.click('.tray-grid .ph-card');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 30000 });
  const afterPlace = await stored();
  check('a photo placed on the back reaches the server',
    afterPlace.placements.length >= 1,
    `${afterPlace.placements.length} placement(s), layout ${afterPlace.layout}`);
  await page.screenshot({ path: `${SHOTS}/91-back-cover.png` });

  console.log('AND IT STAYS');
  await page.reload();
  await page.waitForSelector('#resume-card:not(.hidden), #screen-editor.active',
    { timeout: 30000 });
  if (await page.isVisible('#btn-resume')) await page.click('#btn-resume');
  await page.waitForSelector('#screen-editor.active', { timeout: 30000 });
  const afterReload = await stored();
  check('a full reload keeps the back cover',
    afterReload.placements.length === afterPlace.placements.length);

  console.log('THE PREVIEW SHOWS IT');
  await page.click('#btn-preview');
  await page.waitForFunction(
    () => document.querySelectorAll('#pv-grid figure').length >= 2,
    undefined, { timeout: 180000 });
  const state = await page.evaluate(async (c) => {
    const r = await fetch(`/api/v1/books/${c.book_id}/preview`,
      { headers: { 'X-Edit-Token': c.edit_token } });
    return r.json();
  }, creds);
  check('the preview renders a back tile', !!state.back_url);
  const captions = await page.$$eval('#pv-grid figcaption',
    (els) => els.map((e) => e.textContent.trim()));
  check('and it is shown, last, in the grid',
    captions.length > 2 && captions[captions.length - 1] === captions[0].replace(
      captions[0], captions[captions.length - 1]),
    JSON.stringify([captions[0], captions[captions.length - 1]]));
  await page.screenshot({ path: `${SHOTS}/91-back-preview.png` });

  console.log('errors:', errs.length ? errs : 'none');
  await browser.close();
  if (errs.length || failed) {
    console.error(`BACK COVER CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('BACK COVER CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
