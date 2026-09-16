/* A95: a cover design can carry artwork for the BACK panel too.
 *
 * Three things have to be true, and they live in three different places:
 *
 *   1. the CONSOLE can put a back on a design — including on one that
 *      already exists, without re-uploading the front;
 *   2. the EDITOR draws it on the back panel, so the customer sees what
 *      they will get;
 *   3. the PREVIEW renders a back tile for it even when the customer has
 *      put no photos there — the preview is the contract, and a designed
 *      back that never appears is a panel confirmed unseen.
 *
 * Needs ADMIN_TOKEN=dev-admin (the dev server's default).
 *
 *   node checks/backart.js
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const BASE = 'http://127.0.0.1:8000';
const TOKEN = 'dev-admin';
const SHOTS = path.join(__dirname, '..', 'shots');
const FRONT = path.join(__dirname, '..', 'fixtures', 'artwork-hearts.png');
const BACK = path.join(__dirname, '..', 'fixtures', 'artwork-back.png');
const PHOTO = path.join(__dirname, '..', 'fixtures', 'photo00.jpg');

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

/* A front-only design, so the console has something to add a back TO. */
async function seedFrontOnly(slug) {
  const form = new FormData();
  form.append('slug', slug);
  form.append('name', 'Back art test');
  form.append('book_types', 'travel');
  form.append('sort_order', '5');
  form.append('bg_color', '#1d4d85');
  form.append('artwork',
    new Blob([fs.readFileSync(FRONT)], { type: 'image/png' }), 'a.png');
  const resp = await fetch(`${BASE}/api/v1/admin/cover-designs`, {
    method: 'POST', headers: { 'X-Admin-Token': TOKEN }, body: form,
  });
  if (!resp.ok) {
    throw new Error(`could not seed ${slug}: ${resp.status} — is ADMIN_TOKEN `
      + `set to "${TOKEN}"?`);
  }
  return resp.json();
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const slug = `backart${Date.now().toString().slice(-6)}`;
  const seeded = await seedFrontOnly(slug);
  check('a design starts with no back',
    !seeded.back_display_url, JSON.stringify(seeded.back_display_url));

  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 950 } });
  const page = await ctx.newPage();
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e)));

  // ---------------------------------------------------------------- console
  console.log('THE CONSOLE PUTS A BACK ON AN EXISTING DESIGN');
  await page.goto(`${BASE}/admin/`);
  await page.fill('#login-token', TOKEN);
  await page.click('#login-form button[type=submit]');
  await page.waitForSelector('#screen-main.active, #tab-orders', { timeout: 20000 });
  await page.click('.tab[data-tab="designs"]');
  // Exactly this design, never "the first row". A comma-separated fallback
  // here resolves by DOM order, not in order of preference, so it quietly
  // opened a DIFFERENT design left behind by an earlier run — and the check
  // then reported on that one instead.
  const row = `#design-list .design-row[data-slug="${slug}"]`;
  await page.waitForSelector(row, { timeout: 20000 });
  await page.click(row);
  await page.waitForSelector('#edit-form:not(.hidden)', { timeout: 20000 });

  check('the back preview is hidden before there is a back',
    await page.isHidden('#back-col'));

  await page.setInputFiles('#f-back-artwork', BACK);
  await page.waitForSelector('#back-col:not(.hidden)', { timeout: 20000 });
  check('choosing a file shows the back preview at once', true);
  check('no size complaint about a correctly sized file',
    await page.isHidden('#back-note'));
  await page.screenshot({ path: `${SHOTS}/95-console-back.png` });

  await page.click('#btn-save');
  // Wait for the console to settle rather than for the network: the same
  // lesson as A85/A90 — a re-enabled button is what says the save landed.
  await page.waitForFunction(
    () => !document.getElementById('btn-save').disabled, undefined,
    { timeout: 30000 });

  const saved = await (await fetch(`${BASE}/api/v1/cover-designs?book_type=travel`,
    { headers: { 'X-Admin-Token': TOKEN } })).json();
  const mine = (saved.designs || []).find((d) => d.slug === slug);
  check('the saved design now has back artwork',
    !!(mine && mine.back_display_url));

  // The front must be untouched by all of this.
  check('and still has its front artwork', !!(mine && mine.display_url));

  // ---------------------------------------------------------------- editor
  console.log('THE EDITOR DRAWS IT ON THE BACK PANEL');
  await page.goto(`${BASE}/editor/`);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/editor/`);
  await page.click('.btype[data-btype="travel"]');
  await page.waitForFunction(
    () => document.querySelector('[data-tier-pages]').textContent,
    undefined, { timeout: 30000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#design-step:not(.hidden)', { timeout: 30000 });
  await page.click(`.design-card[data-design="${slug}"]`);
  await page.waitForSelector('#screen-editor.active', { timeout: 30000 });

  // Straight to the back panel — the last item in the strip.
  await page.click('#filmstrip .film-item:last-child');
  await page.waitForFunction(
    () => document.getElementById('page-canvas').classList.contains('back-mode'),
    undefined, { timeout: 20000 });
  const backArt = await page.$eval('#page-canvas', (el) => {
    const img = el.querySelector('img.cover-art');
    return img ? img.getAttribute('src') : null;
  });
  check('the back panel shows the design artwork', !!backArt);
  await page.screenshot({ path: `${SHOTS}/95-editor-back.png` });

  const stripArt = await page.$$eval('#filmstrip .film-item:last-child img.film-art',
    (els) => els.length);
  check('and the filmstrip tile shows it too', stripArt === 1, `${stripArt} imgs`);

  // ---------------------------------------------------------------- preview
  console.log('AND THE PREVIEW SHOWS THE BACK WITH NO PHOTOS ON IT');
  await page.setInputFiles('#file-input', [PHOTO]);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('1 '),
    undefined, { timeout: 120000 });
  await page.click('#btn-autofill');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 60000 });

  await page.click('#btn-preview');
  await page.waitForSelector('#screen-preview.active', { timeout: 30000 });
  await page.waitForFunction(() => {
    const figs = document.querySelectorAll('#pv-grid figure').length;
    const status = document.getElementById('pv-status').textContent.trim();
    return figs > 0 || (status && !document.getElementById('pv-status')
      .classList.contains('busy'));
  }, undefined, { timeout: 240000 });

  // The back tile is the one the old code would not have made: nothing was
  // placed on the back, so before A95 there was simply nothing to show.
  const backTile = await page.$$eval('#pv-grid figure', (figs) => figs.filter(
    (f) => /back/i.test(f.textContent || '')).length);
  check('the preview includes a back tile although no photo is on it',
    backTile > 0, `${backTile} back tiles`);
  await page.screenshot({ path: `${SHOTS}/95-preview-back.png`, fullPage: true });

  console.log('errors:', errs.length ? errs : 'none');
  await browser.close();
  if (errs.length || failed) {
    console.error(`BACK ARTWORK CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('BACK ARTWORK CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
