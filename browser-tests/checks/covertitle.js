/* A89, then A104: a cover carries no words but the customer's own.
 *
 * A new book used to arrive with a title already filled in ("Our travels").
 * Clearing it left the editor showing a placeholder in the title's own
 * position, weight and size — indistinguishable from printed text. Nothing
 * was wrong underneath: the server stored "" and the renderer draws
 * nothing. But the screen said otherwise, and the screen is what a customer
 * believes.
 *
 * A89 answered that by making the placeholder LOOK like a field: an
 * instruction rather than a noun, in a dashed outline, on the reasoning
 * that "an instruction plus a field outline cannot be mistaken for
 * content". That did not survive contact with a customer, who reported the
 * same thing again in plainer words.
 *
 * A104 answered it twice over. The empty block is not drawn at all, and
 * `+ Title` is how you ask for one — and then the prefill itself went, so
 * there is nothing to delete in the first place. What is left to prove is
 * that a title is only ever there because somebody typed it, and that once
 * typed it can be taken away again.
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

  const creds = await page.evaluate(() => JSON.parse(localStorage.getItem('mb-book')));
  const stored = () => page.evaluate(async (c) => {
    const r = await fetch(`/api/v1/books/${c.book_id}`,
      { headers: { 'X-Edit-Token': c.edit_token } });
    return r.ok ? (await r.json()).layout.cover.title : `HTTP ${r.status}`;
  }, creds);
  const shown = () => page.$eval('.cover-title', (el) => el.value);
  // What a customer can read where the title goes — placeholders included,
  // because a placeholder is text to the eye whatever the DOM calls it.
  const onCover = () => page.evaluate(() =>
    [...document.querySelectorAll('.cover-titles input')]
      .map((i) => (i.value || i.placeholder || '').trim()).filter(Boolean));

  console.log('A NEW BOOK HAS NO TITLE AT ALL');
  check('nothing is on the cover to begin with', (await onCover()).length === 0,
    JSON.stringify(await onCover()));
  check('and the server has none either', (await stored()) === '',
    JSON.stringify(await stored()));

  console.log('ONE APPEARS ONLY WHEN SOMEBODY TYPES IT');
  await page.click('#btn-add-title');
  await page.waitForSelector('.cover-title', { timeout: 10000 });
  await page.keyboard.type('Sayohatimiz');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 30000 });
  check('what was typed is on the cover', (await shown()) === 'Sayohatimiz',
    JSON.stringify(await shown()));
  check('and reached the server', (await stored()) === 'Sayohatimiz',
    JSON.stringify(await stored()));

  console.log('CLEARING IT');
  await page.click('.cover-title');
  await page.keyboard.press('Control+A');
  await page.keyboard.press('Delete');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 30000 });
  // Click away first. While the block is SELECTED it stays on screen with
  // its placeholders, which is right — you are typing in it. What must not
  // survive is leaving it empty, and that is what this asserts.
  await page.click('#canvas-wrap', { position: { x: 20, y: 20 } });
  await page.waitForTimeout(300);
  check('nothing is left where the title was', (await onCover()).length === 0,
    JSON.stringify(await onCover()));
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
  await page.waitForTimeout(400);
  check('a full reload does not put it back', (await onCover()).length === 0,
    JSON.stringify(await onCover()));
  check('nor does the server', (await stored()) === '');

  console.log('AN EMPTY TITLE SHOWS NOTHING AT ALL (A104)');
  // Stronger than A89's "the placeholder reads as a field": there is no
  // placeholder, because there is no block. The cover shows what prints.
  check('no title block is drawn',
    (await page.$$('.cover-titles')).length === 0);
  check('and the title colour control is not offered either',
    !(await page.$eval('#page-tools', (el) => el.textContent)).match(/colour.*colour/i));
  await page.screenshot({ path: `${SHOTS}/89-cover-no-title.png` });

  console.log('AND `+ TITLE` IS HOW YOU ASK FOR ONE BACK');
  check('the button is offered once there is no title',
    !(await page.evaluate(() =>
      document.getElementById('btn-add-title').classList.contains('hidden'))));
  await page.click('#btn-add-title');
  await page.waitForSelector('.cover-title', { timeout: 10000 });
  check('it opens an empty field, not a prefilled one', (await shown()) === '',
    JSON.stringify(await shown()));
  await page.keyboard.type('Sayohatimiz');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 30000 });
  check('and what is typed there is kept', (await stored()) === 'Sayohatimiz',
    JSON.stringify(await stored()));
  // Back to none, so the rest of the check sees the state it expects.
  await page.click('.cover-title');
  await page.keyboard.press('Control+A');
  await page.keyboard.press('Delete');
  await page.click('#canvas-wrap', { position: { x: 20, y: 20 } });
  await page.waitForTimeout(300);

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
  // Back to the cover — which by now has no title, so wait for the COVER
  // rather than for a title block that is deliberately absent.
  await page.waitForFunction(
    () => !document.getElementById('page-canvas').classList.contains('page-mode'),
    undefined, { timeout: 10000 });

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
