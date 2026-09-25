/* The language can be changed from inside the editor.
 *
 * It used to live only on the start screen, which put the choice before
 * the customer had seen anything — and once the editor was open there was
 * no way back to it. Picking the wrong language and noticing two uploads
 * later meant abandoning the book, so the cost of a mis-tap was the whole
 * session.
 *
 * The assertions that matter are not "a select exists":
 *
 *   - the editor CHROME changes, so the switch did something;
 *   - the BOOK SURVIVES it, which is the whole point — a language switch
 *     that cleared the photos would be worse than no switch at all;
 *   - the two selects AGREE afterwards, checked by coming back to the
 *     start screen and reading the visible one rather than the hidden copy;
 *   - the bar still fits a phone, since it now carries one more control.
 *
 *   node checks/editorlang.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:8000';
const SHOTS = path.join(__dirname, '..', 'shots');
const FIXTURES = path.join(__dirname, '..', 'fixtures');
const PHOTOS = [0, 1].map((n) => path.join(FIXTURES, `photo0${n}.jpg`));

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  const noise = watchPage(page, errors);

  console.log('INTO A BOOK, IN ENGLISH');
  await page.goto(`${BASE}/editor/`);
  await page.waitForSelector('.btype:not([disabled])', { timeout: 15000 });
  await page.evaluate(() => localStorage.setItem('sb-lang', 'en'));
  await page.goto(`${BASE}/editor/`);
  await page.waitForSelector('.btype:not([disabled])', { timeout: 15000 });
  await page.click('.btype[data-btype="memory"]');
  await page.waitForSelector('.tier:not([disabled])', { timeout: 10000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active', { timeout: 15000 });

  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('2 '),
    undefined, { timeout: 120000 });

  check('the editor bar has a language selector',
    await page.isVisible('#ed-lang-select'));
  const before = (await page.textContent('#btn-autofill')).trim();
  console.log(`   auto-fill reads: ${before}`);

  console.log('\nSWITCHED TO RUSSIAN, MID-BOOK');
  await page.selectOption('#ed-lang-select', 'ru');
  await page.waitForFunction(() => document.documentElement.lang === 'ru',
    undefined, { timeout: 10000 });
  const after = (await page.textContent('#btn-autofill')).trim();
  console.log(`   auto-fill reads: ${after}`);
  check('the editor chrome is translated', after !== before && /[А-Яа-я]/.test(after), after);
  check('and it is not an untranslated key', !/^tool\./.test(after), after);

  // The reason this control was missing is the reason it has to be safe:
  // somebody switches language three uploads in, not before starting.
  const trayNow = (await page.textContent('#tray-count')).trim();
  check('the photos are still there', /^2\b/.test(trayNow), trayNow);
  check('and the editor is still the active screen',
    await page.isVisible('#screen-editor.active'));
  await page.screenshot({ path: path.join(SHOTS, 'editorlang-ru.png') });

  console.log('\nON A PHONE');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(200);
  const bar = await page.evaluate(() => {
    const el = document.querySelector('.ed-bar');
    const sel = document.getElementById('ed-lang-select');
    const r = sel.getBoundingClientRect();
    return {
      scrolls: el.scrollWidth > el.clientWidth + 1,
      selVisible: r.width > 0 && r.height > 0,
      selRight: r.right,
      pageOverflows: document.documentElement.scrollWidth
        > document.documentElement.clientWidth + 1,
    };
  });
  check('the selector is visible at phone width', bar.selVisible, JSON.stringify(bar));
  check('it sits inside the viewport', bar.selRight <= 390, `right=${bar.selRight}`);
  check('the bar wraps rather than scrolling sideways', !bar.scrolls);
  check('and the page has no horizontal scroll', !bar.pageOverflows);
  await page.screenshot({ path: path.join(SHOTS, 'editorlang-phone.png') });

  console.log('\nBACK ON THE START SCREEN, SAME SESSION');
  // This is what covers the mirroring between the two selects. The fresh
  // visit below would pass on localStorage alone, so it proves nothing
  // about them agreeing inside one session.
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.click('#ed-back');
  await page.waitForSelector('#screen-start.active', { timeout: 15000 });
  check('the start screen selector followed the editor',
    await page.inputValue('#lang-select') === 'ru',
    await page.inputValue('#lang-select'));

  console.log('\nAND A FRESH VISIT REMEMBERS');
  // Read the visible select on a fresh visit rather than the hidden copy:
  // the question is what the next customer session shows, not what an
  // off-screen element happens to hold.
  const fresh = await ctx.newPage();
  await fresh.goto(`${BASE}/editor/`);
  await fresh.waitForSelector('.btype:not([disabled])', { timeout: 15000 });
  check('the start screen selector shows the language chosen in the editor',
    await fresh.inputValue('#lang-select') === 'ru',
    await fresh.inputValue('#lang-select'));
  check('and the start screen is in Russian',
    await fresh.evaluate(() => document.documentElement.lang) === 'ru');

  console.log('\nerrors:', errors.length ? errors : 'none');
  if (noise.length) {
    console.log(`ignored ${noise.length} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`EDITOR LANGUAGE CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('EDITOR LANGUAGE CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
