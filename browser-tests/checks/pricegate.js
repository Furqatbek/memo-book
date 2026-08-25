/* A74: what a customer sees while the prices are still placeholders.
 *
 * The server refusal is unit-tested. What that cannot show is whether the
 * person actually finds out — the failure this guards against is someone
 * spending an evening on a book and hitting a 503 at the last step. So this
 * drives the real editor and asserts on the screen: the notice is there, in
 * their language, the prices are still readable, and checkout says something
 * that makes sense rather than "something went wrong".
 *
 * Needs a server started with PRICES_CONFIRMED=false, which is the opposite
 * of every other check — the runner knows.
 */
const { chromium } = require('playwright');
const path = require('path');
const SHOTS = path.join(__dirname, '..', 'shots');
const BASE = 'http://127.0.0.1:8000';
const PHOTO = path.join(__dirname, '..', 'fixtures', 'photo00.jpg');

let failures = 0;
function check(label, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${label}${detail !== undefined ? `  ${detail}` : ''}`);
  if (!ok) failures++;
}

(async () => {
  // The check is meaningless against a server that is happily selling.
  const quoted = await (await fetch(`${BASE}/api/v1/prices`)).json();
  if (quoted.confirmed !== false) {
    throw new Error('the server has PRICES_CONFIRMED on — start it with '
      + 'PRICES_CONFIRMED=false for this check');
  }

  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1240, height: 950 } })).newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto(`${BASE}/editor/`);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/editor/`);
  await page.waitForFunction(() => document.querySelector('[data-tier-price]').textContent,
    undefined, { timeout: 10000 });

  console.log('THE START SCREEN');
  const notice = page.locator('#prices-draft');
  check('the notice is on screen before anything is chosen',
    await notice.isVisible());
  const words = (await notice.textContent()).trim().replace(/\s+/g, ' ');
  check('it says the prices are not final', /not final/i.test(words),
    JSON.stringify(words));

  // Quoting the price is the deliberate half of the decision: a blank tier
  // picker would tell the customer less, not more.
  const shown = await page.$$eval('[data-tier-price]',
    (els) => els.map((e) => e.textContent.trim()).filter(Boolean));
  check('the prices are still shown, not hidden', shown.length === 4,
    JSON.stringify(shown));
  await page.screenshot({ path: SHOTS + '/95-price-gate-start.png' });

  console.log('IN EVERY LANGUAGE');
  for (const [lang, needle] of [['ru', /не окончательные/i],
                                ['uz', /yakuniy emas/i],
                                ['uz-cyrl', /якуний эмас/i],
                                ['kaa', /juwmaqlanba/i]]) {
    await page.selectOption('#lang-select', lang);
    await page.waitForFunction(
      (l) => document.documentElement.lang === l
        || document.getElementById('prices-draft').textContent.trim().length > 0,
      lang, { timeout: 5000 });
    const text = (await page.textContent('#prices-draft')).trim();
    check(`${lang} is translated, not falling back to English`,
      needle.test(text), JSON.stringify(text.slice(0, 48) + '…'));
  }
  await page.selectOption('#lang-select', 'en');

  console.log('ALL THE WAY TO CHECKOUT');
  await page.click('.btype[data-btype="memory"]');
  await page.waitForFunction(() => document.querySelector('[data-tier-pages]').textContent,
    undefined, { timeout: 10000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');
  check('the book can still be started and edited', true);

  // One photo is enough to prove the book survives: the refusal must not
  // lock it or throw the customer's work away.
  await page.setInputFiles('#file-input', [PHOTO]);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('1 '),
    undefined, { timeout: 120000 });
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 20000 });

  const creds = await page.evaluate(() => JSON.parse(localStorage.getItem('mb-book')));
  const book = await (await fetch(`${BASE}/api/v1/books/${creds.book_id}`,
    { headers: { 'X-Edit-Token': creds.edit_token } })).json();
  check('the book is saved and still a draft', book.status === 'draft',
    book.status);

  // Go at the checkout endpoint the way the page does, since reaching the
  // form needs a finished book. What matters here is the shape of the answer.
  const resp = await fetch(`${BASE}/api/v1/books/${creds.book_id}/checkout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Edit-Token': creds.edit_token },
    body: JSON.stringify({ name: 'Price Gate', phone: '+998 90 000-00-00',
                           address: 'Tashkent', confirmed_preview: true }),
  });
  const body = await resp.json();
  check('checkout is refused', resp.status === 503, resp.status);
  check('with a code the editor knows',
    body.error && body.error.code === 'PRICES_NOT_CONFIRMED',
    body.error && body.error.code);
  check('and a message a customer can read',
    /charged/i.test((body.error || {}).message || ''),
    JSON.stringify((body.error || {}).message));

  const after = await (await fetch(`${BASE}/api/v1/books/${creds.book_id}`,
    { headers: { 'X-Edit-Token': creds.edit_token } })).json();
  check('the refusal left the book editable', after.status === 'draft',
    after.status);

  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) throw new Error('page errors');
  if (failures) throw new Error(`${failures} checks failed`);
  console.log('PRICE GATE CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
