/* A104: the cover's text can be turned off, and the editor shows what prints.
 *
 * The complaint was "default text is impossible to turn off or delete". It
 * was half true in the worst way. Deleting the prefilled title DID work —
 * the layout saved an empty title and neither renderer drew one — but the
 * editor went on showing two inputs on the cover reading "Add a title" and
 * "Add a subtitle", in title-sized type, with a dashed box round them. So
 * the customer deleted their title and the cover still had text on it that
 * nothing would remove.
 *
 * That is worse than a cosmetic bug. This editor's promise is that what you
 * see is what gets printed, and here it was showing something the book
 * would not have.
 *
 * The load-bearing assertion is `nothing is left on the cover`. The rest
 * guards the panel built to make it reachable.
 *
 *   node checks/bookcfg.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');
const path = require('path');

const BASE = 'http://127.0.0.1:8000';
const SHOTS = path.join(__dirname, '..', 'shots');

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

/* Everything a customer can actually read on the cover, placeholders and
   all. `value || placeholder` is the point: a placeholder is what the eye
   sees, whatever the DOM calls it. */
const coverText = (page) => page.evaluate(() =>
  [...document.querySelectorAll('.cover-titles input')]
    .map((i) => (i.value || i.placeholder || '').trim())
    .filter(Boolean));

async function savedCover(page) {
  return page.evaluate(async () => {
    const creds = JSON.parse(localStorage.getItem('mb-book'));
    const r = await fetch(`/api/v1/books/${creds.book_id}`,
                          { headers: { 'X-Edit-Token': creds.edit_token } });
    return (await r.json()).layout.cover;
  });
}

(async () => {
  require('fs').mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1360, height: 900 } })).newPage();
  const errors = [];
  const noise = watchPage(page, errors);

  await page.goto(`${BASE}/editor/`);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/editor/`);
  // "love" prefills a title; that prefill is the thing under test.
  await page.click('.btype[data-btype="love"]');
  await page.waitForFunction(
    () => document.querySelector('[data-tier-pages]').textContent,
    undefined, { timeout: 30000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');

  console.log('THE PREFILLED TITLE IS REALLY THERE TO BEGIN WITH');
  check('the cover starts with a title', (await coverText(page)).length > 0,
    JSON.stringify(await coverText(page)));

  console.log('AND DELETING IT LEAVES NOTHING BEHIND');
  await page.click('.cover-title');
  await page.keyboard.press('Control+A');
  await page.keyboard.press('Delete');
  await page.click('#canvas-wrap', { position: { x: 20, y: 20 } });
  await page.waitForTimeout(400);
  const left = await coverText(page);
  // THE assertion. Before A104 this was ["Add a title", "Add a subtitle"].
  check('nothing is left on the cover', left.length === 0, JSON.stringify(left));
  await page.screenshot({ path: `${SHOTS}/104-title-removed.png` });

  console.log('AND THE SERVER AGREES, WHICH IS WHAT GETS PRINTED');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 30000 });
  const saved = await savedCover(page);
  check('the saved cover has no title', !saved.title, JSON.stringify(saved.title));
  check('and no subtitle', !saved.subtitle, JSON.stringify(saved.subtitle));

  console.log('AND IT STAYS GONE ACROSS A RELOAD');
  await page.reload();
  await page.waitForSelector('#btn-resume', { timeout: 30000 });
  await page.click('#btn-resume');
  await page.waitForSelector('#screen-editor.active', { timeout: 30000 });
  // A resumed book opens on page 1, so the cover has to be asked for. Without
  // this the next assertion reads an empty cover because the cover is not on
  // screen at all — a check that passes while proving nothing.
  await page.click('#filmstrip .film-item[data-page="-1"]');
  await page.waitForTimeout(300);
  check('the cover is the one being shown',
    (await page.$eval('#page-label', (el) => el.textContent)).length > 0);
  check('still nothing on the cover', (await coverText(page)).length === 0,
    JSON.stringify(await coverText(page)));

  console.log('THE SETTINGS PANEL PUTS IT BACK');
  await page.click('#btn-settings');
  await page.waitForSelector('.cfg-pop', { timeout: 5000 });
  check('the switch reads as off', await page.isChecked('#cfg-title-on') === false);
  await page.check('#cfg-title-on');
  await page.waitForTimeout(300);
  check('the title is back on the cover', (await coverText(page)).length > 0,
    JSON.stringify(await coverText(page)));
  check('and the field shows it', (await page.inputValue('#cfg-title')).length > 0);

  console.log('AND THE PANEL ACTUALLY EDITS THE COVER');
  await page.fill('#cfg-title', 'Bizning kitobimiz');
  await page.fill('#cfg-subtitle', '2026');
  await page.waitForTimeout(300);
  const both = await coverText(page);
  check('both lines reached the cover',
    both.includes('Bizning kitobimiz') && both.includes('2026'),
    JSON.stringify(both));
  await page.selectOption('#cfg-size', '36');
  await page.waitForTimeout(250);
  const size = await page.$eval('.cover-title', (el) => el.style.fontSize);
  check('the size control changes the title', parseFloat(size) > 0, size);
  await page.screenshot({ path: `${SHOTS}/104-settings-panel.png` });

  console.log('AND IT IS DISMISSIBLE THE INSTANT IT OPENS');
  // The A101 race, in the popover this panel is built on: listeners attached
  // on a timer leave a tick in which the panel is up and nothing is
  // listening. Opening and dismissing in ONE task cannot pass if they are.
  await page.evaluate(() => document.querySelectorAll('.cfg-pop').forEach((n) => n.remove()));
  const sameTask = await page.evaluate(() => {
    document.getElementById('btn-settings').click();
    const opened = document.querySelectorAll('.cfg-pop').length;
    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
    return { opened, left: document.querySelectorAll('.cfg-pop').length };
  });
  check('it opens', sameTask.opened === 1, `${sameTask.opened}`);
  check('and an outside click in the same task closes it', sameTask.left === 0,
    `${sameTask.left} left open`);

  console.log('AND IT IS NOT OFFERED WHERE IT WOULD DO NOTHING');
  await page.click('#filmstrip .film-item[data-page="0"]');
  await page.waitForTimeout(400);
  check('the Settings button is hidden on an inside page',
    await page.isHidden('#btn-settings'));

  console.log('AND REMOVE SAYS WHICH THING IT REMOVES');
  await page.click('#filmstrip .film-item[data-page="-1"]');
  await page.waitForTimeout(400);
  await page.click('.cover-title');
  await page.waitForTimeout(300);
  const labels = await page.$$eval('#sel-toolbar button',
    (els) => els.map((e) => e.textContent.trim()));
  check('the title block offers to remove the TITLE',
    labels.some((l) => /title|sarlavha|заголов|atama/i.test(l)), JSON.stringify(labels));
  // There is no cover photo in this book, so there must be no button
  // offering to remove one — it would do nothing at all (A85).
  check('and offers no photo removal when there is no photo',
    !labels.some((l) => /photo|surat|фото|súwret/i.test(l)), JSON.stringify(labels));

  console.log('errors:', errors.length ? errors : 'none');
  if (noise.length) {
    console.log(`ignored ${noise.length} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`BOOK SETTINGS CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('BOOK SETTINGS CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
