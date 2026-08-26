/* A84: the screens on the way in and the way out.
 *
 * The look is a judgement call and this cannot check it. What it can check
 * is the part of the new work that could be silently WRONG rather than
 * merely ugly: the checkout summary quotes a price, and a price on a
 * checkout page that disagrees with what the server will charge is worse
 * than no price at all.
 *
 * Also here because they are cheap: the step rail has to advance (a
 * progress indicator stuck on step one is worse than none), and the perks
 * have to be translated rather than showing raw keys — this project has
 * shipped raw translation keys to production before.
 */
const { chromium } = require('playwright');
const path = require('path');
const BASE = 'http://127.0.0.1:8000';
const SHOTS = path.join(__dirname, '..', 'shots');

let failures = 0;
function check(label, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${label}${detail !== undefined ? `  ${detail}` : ''}`);
  if (!ok) failures++;
}

const stepState = (page) => page.$$eval('#start-steps li', (els) => els.map(
  (e) => `${e.dataset.step}:${e.classList.contains('done') ? 'done'
    : e.classList.contains('on') ? 'on' : '-'}`).join(' '));

(async () => {
  const prices = await (await fetch(`${BASE}/api/v1/prices`)).json();
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto(`${BASE}/editor/`);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/editor/`);
  await page.waitForFunction(() => document.querySelector('[data-tier-price]').textContent,
    undefined, { timeout: 15000 });

  console.log('THE STEP RAIL');
  check('it starts on the first step', await stepState(page) === 'type:on tier:- design:-',
    await stepState(page));

  await page.click('.btype[data-btype="travel"]');
  await page.waitForFunction(() => document.querySelector('[data-tier-pages]').textContent,
    undefined, { timeout: 10000 });
  check('choosing a type ticks it and moves on',
    await stepState(page) === 'type:done tier:on design:-', await stepState(page));

  console.log('THE PERKS');
  const perks = await page.$$eval('.perks li b', (els) => els.map((e) => e.textContent.trim()));
  check('all three are shown', perks.length === 3, JSON.stringify(perks));
  check('and translated, not raw keys',
    perks.every((p) => p && !p.includes('perk.')), JSON.stringify(perks));

  console.log('THE CHECKOUT SUMMARY');
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) {
    check('the cover step ticks the two before it',
      await stepState(page) === 'type:done tier:done design:on', await stepState(page));
    await page.click('#design-skip');
  }
  await page.waitForSelector('#screen-editor.active');

  // Reach checkout without a finished book: the summary is rendered from
  // what the editor already knows, so it must not need one.
  await page.evaluate(() => {
    document.getElementById('screen-editor').classList.remove('active');
    document.getElementById('pv-checkout').removeAttribute('disabled');
  });
  await page.evaluate(() => document.getElementById('pv-checkout').click());
  await page.waitForSelector('#screen-checkout.active', { timeout: 15000 });

  const shown = (await page.textContent('#co-sum-price')).replace(/\s| /g, '');
  const expected = String(prices.prices['16'] / 100).replace(/\B(?=(\d{3})+(?!\d))/g, '');
  check('the summary quotes a price at all', shown.length > 0, JSON.stringify(shown));
  check('and it is the price the server will charge',
    shown.replace(/\D/g, '') === String(prices.prices['16'] / 100),
    `page=${shown} server=${prices.prices['16'] / 100}`);
  check('the summary names the book type',
    (await page.textContent('#co-sum-type')).trim().length > 0);
  check('and its size', /32/.test(await page.textContent('#co-sum-size')),
    JSON.stringify((await page.textContent('#co-sum-size')).trim()));
  await page.screenshot({ path: SHOTS + '/97-checkout-summary.png' });

  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) throw new Error('page errors');
  if (failures) throw new Error(`${failures} checks failed`);
  console.log('START FLOW CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
