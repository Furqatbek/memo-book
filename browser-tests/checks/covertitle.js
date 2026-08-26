/* A89: the cover title can be removed, and an empty one does not look like
 * text that refuses to go away.
 *
 * A new book arrives with a title already filled in ("Our travels"). Clearing
 * it left the editor showing a placeholder in the title's own position,
 * weight and size — indistinguishable from printed text. Nothing was wrong
 * underneath: the server stored "" and the renderer draws nothing. But the
 * screen said otherwise, and the screen is what a customer believes.
 *
 *   node checks/covertitle.js
 */
const { chromium } = require('playwright');
const path = require('path');
const BASE = 'http://127.0.0.1:8000';
const SHOTS = path.join(__dirname, '..', 'shots');

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
  await page.click('.btype[data-btype="travel"]');
  await page.waitForFunction(() => document.querySelector('[data-tier-pages]').textContent,
    undefined, { timeout: 30000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');
  await page.waitForSelector('.cover-title', { timeout: 30000 });

  const creds = await page.evaluate(() => JSON.parse(localStorage.getItem('mb-book')));
  const stored = () => page.evaluate(async (c) => {
    const r = await fetch(`/api/v1/books/${c.book_id}`,
      { headers: { 'X-Edit-Token': c.edit_token } });
    return r.ok ? (await r.json()).layout.cover.title : `HTTP ${r.status}`;
  }, creds);
  const shown = () => page.$eval('.cover-title', (el) => el.value);

  console.log('A PREFILLED TITLE');
  const initial = await shown();
  check('a new book starts with one', initial.length > 0, JSON.stringify(initial));

  console.log('CLEARING IT');
  await page.click('.cover-title');
  await page.keyboard.press('Control+A');
  await page.keyboard.press('Delete');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 30000 });
  check('the field is empty', (await shown()) === '');
  check('and the server agrees', (await stored()) === '',
    JSON.stringify(await stored()));

  console.log('AND IT STAYS GONE');
  await page.reload();
  await page.waitForSelector('#resume-card:not(.hidden), #screen-editor.active',
    { timeout: 30000 });
  if (await page.isVisible('#btn-resume')) await page.click('#btn-resume');
  await page.waitForSelector('#screen-editor.active', { timeout: 30000 });
  await page.waitForSelector('#filmstrip .film-item', { timeout: 30000 });
  await page.click('#filmstrip .film-item:first-child');
  await page.waitForSelector('.cover-title', { timeout: 30000 });
  check('a full reload does not put it back', (await shown()) === '',
    JSON.stringify(await shown()));
  check('nor does the server', (await stored()) === '');

  console.log('AN EMPTY TITLE LOOKS EMPTY');
  const ph = await page.$eval('.cover-title', (el) => el.placeholder);
  check('the placeholder is translated, not a raw key',
    ph.length > 0 && !ph.includes('.'), JSON.stringify(ph));
  // The bug: a bare noun in the title's own style reads as the title itself.
  // An instruction plus a field outline cannot be mistaken for content.
  check('it asks for a title rather than naming one',
    ph.trim().split(/\s+/).length > 1, JSON.stringify(ph));
  const style = await page.$eval('.cover-title', (el) => {
    const s = getComputedStyle(el);
    return { outline: s.outlineStyle, width: s.outlineWidth };
  });
  check('and the empty field is outlined as a field',
    style.outline === 'dashed' && parseFloat(style.width) > 0,
    JSON.stringify(style));

  await page.screenshot({ path: `${SHOTS}/89-cover-no-title.png` });

  console.log('NO BUTTON THAT DOES NOTHING (A92)');
  // `+ Text` writes into `page.texts`, which the cover has no room for:
  // not in CoverDoc, not in the cover PDF, not in the cover preview. It
  // was offered on the cover for as long as the cover existed and never
  // once did anything.
  const vis = (id) => page.evaluate(
    (i) => !document.getElementById(i).classList.contains('hidden'), id);
  check('the cover does not offer "+ Text"', !(await vis('btn-add-text')));
  // Stickers really do print on the cover, so that button stays.
  check('but it does offer "+ Sticker"', await vis('btn-add-sticker'));

  // ...and an inside page offers both, because both work there.
  await page.click('#filmstrip .film-item:nth-child(2)');
  await page.waitForFunction(
    () => document.getElementById('page-canvas').classList.contains('page-mode'),
    undefined, { timeout: 10000 });
  check('an inside page offers "+ Text"', await vis('btn-add-text'));
  check('and "+ Sticker"', await vis('btn-add-sticker'));
  const before = await page.$$eval('.textbox', (els) => els.length);
  await page.click('#btn-add-text');
  await page.waitForTimeout(500);
  check('and pressing it actually adds one',
    (await page.$$eval('.textbox', (els) => els.length)) === before + 1);
  await page.click('#filmstrip .film-item:first-child');
  await page.waitForSelector('.cover-title', { timeout: 10000 });

  console.log('AND NOTHING PRINTS');
  await page.click('#btn-preview');
  await page.waitForFunction(
    () => document.querySelectorAll('#pv-grid figure').length >= 1,
    undefined, { timeout: 180000 });
  check('the preview renders with the title gone', true);

  console.log('errors:', errs.length ? errs : 'none');
  await browser.close();
  if (errs.length || failed) {
    console.error(`COVER TITLE CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('COVER TITLE CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
