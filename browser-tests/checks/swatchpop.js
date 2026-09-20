/* A101: the colour popup is dismissible from the instant it appears.
 *
 * This is the bug that made `freeform` flaky for three sessions. The
 * popup's dismiss listeners were attached in a `setTimeout(..., 0)`, so for
 * one tick after opening it there was a popup on screen and nothing
 * listening for the click or the key that closes it. Anything that tried to
 * close it in that window did nothing — and worse, tore down listeners that
 * were then attached a tick later with no popup to match.
 *
 * Hammering the cycle catches it about once in eighty, which is exactly
 * what a flake is. So the load-bearing assertion here does not hammer: it
 * opens the popup and dismisses it IN THE SAME TASK. A deferred attach
 * cannot possibly have run by then, so the test is deterministic — with the
 * timer restored it fails every time, not one run in eighty.
 *
 *   node checks/swatchpop.js
 */
const { chromium } = require('playwright');
const BASE = 'http://127.0.0.1:8000';

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

const popups = (page) =>
  page.evaluate(() => document.querySelectorAll('.swatch-pop').length);

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1360, height: 850 } })).newPage();
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e)));

  // No photos needed: the cover carries its two colour tools from the start.
  await page.goto(`${BASE}/editor/`);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/editor/`);
  await page.click('.btype[data-btype="memory"]');
  await page.waitForFunction(
    () => document.querySelector('[data-tier-pages]').textContent,
    undefined, { timeout: 30000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');

  const tools = await page.$$('#page-tools .color-tool');
  check('the cover offers its colour tools', tools.length === 2, `${tools.length}`);

  console.log('DISMISSIBLE THE INSTANT IT OPENS');
  // Open and dismiss inside ONE task. A listener attached on a timer cannot
  // have run yet, so this fails deterministically when it is.
  const sameTask = await page.evaluate(() => {
    document.querySelectorAll('#page-tools .color-tool')[0].click();
    const opened = document.querySelectorAll('.swatch-pop').length;
    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
    return { opened, left: document.querySelectorAll('.swatch-pop').length };
  });
  check('it opens', sameTask.opened === 1, `${sameTask.opened} popups`);
  check('and an outside click in the same task closes it',
    sameTask.left === 0, `${sameTask.left} left open`);

  const sameTaskKey = await page.evaluate(() => {
    document.querySelectorAll('#page-tools .color-tool')[0].click();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    return document.querySelectorAll('.swatch-pop').length;
  });
  check('and so does Escape in the same task', sameTaskKey === 0,
    `${sameTaskKey} left open`);

  console.log('AND THROUGH REAL INPUT');
  await page.locator('#page-tools .color-tool').nth(0).click();
  check('a real click opens it', await popups(page) === 1);
  await page.keyboard.press('Escape');
  check('a real Escape closes it', await popups(page) === 0);

  await page.locator('#page-tools .color-tool').nth(0).click();
  await page.mouse.click(5, 5);
  check('a real click elsewhere closes it', await popups(page) === 0);

  await page.locator('#page-tools .color-tool').nth(1).click();
  await page.locator('#page-tools .color-tool').nth(1).click();
  check('pressing the same tool twice toggles it shut',
    await popups(page) === 0);

  console.log('PICKING A COLOUR THEN MOVING ON');
  // The freeform sequence that used to hang: pick on one tool, close, then
  // reach for the next. A popup left open turns the next tool's click into
  // a toggle, and the colour never gets picked.
  for (const [i, colour] of [[0, '#123a5e'], [1, '#ffd700']]) {
    await page.locator('#page-tools .color-tool').nth(i).click();
    await page.waitForSelector('.swatch-pop input[type=color]', { timeout: 10000 });
    await page.$eval('.swatch-pop input[type=color]', (el, v) => {
      el.value = v;
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }, colour);
    await page.keyboard.press('Escape');
    check(`tool ${i}: closed after picking`, await popups(page) === 0);
  }

  console.log('errors:', errs.length ? errs : 'none');
  await browser.close();
  if (errs.length || failed) {
    console.error(`SWATCH POPUP CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('SWATCH POPUP CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
