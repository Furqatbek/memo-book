/* A73: the orders section of the admin console — the operator's daily job.
 *
 * Places a real order as a customer, then does the whole job from the
 * console: find it, confirm the transfer, collect the print files, move it
 * to the printer, ship it, deliver it.
 *
 * Needs a dev server WITHOUT auto-confirm, so an order actually sits in
 * pending_payment and the "transfer arrived" button has something to do:
 *   AUTO_CONFIRM_ORDERS=false python scripts/devserver.py
 */
const { chromium } = require('playwright');
const path = require('path');
const SHOTS = path.join(__dirname, '..', 'shots');
const BASE = 'http://127.0.0.1:8000';
const TOKEN = 'dev-admin';
const PHOTOS = Array.from({ length: 32 }, (_, i) =>
  path.join(__dirname, '..', 'fixtures', `photo${String(i % 16).padStart(2, '0')}.jpg`));

/* Place an order the way a customer does, so the console has something real
   to work on rather than a row inserted behind its back. */
async function placeOrder(page) {
  await page.goto(`${BASE}/editor/`);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/editor/`);
  await page.click('.btype[data-btype="travel"]');
  await page.waitForFunction(() => document.querySelector('[data-tier-pages]').textContent,
    undefined, { timeout: 10000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');

  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('32 '),
    undefined, { timeout: 180000 });
  await page.click('#btn-autofill');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 30000 });
  await page.click('#btn-preview');
  await page.waitForFunction(
    () => document.querySelectorAll('#pv-grid figure').length >= 32,
    undefined, { timeout: 180000 });
  await page.check('#pv-confirm');
  await page.waitForSelector('#pv-checkout:not([disabled])');
  await page.click('#pv-checkout');
  await page.waitForSelector('#screen-checkout.active');
  await page.fill('[name=name]', 'Aziza Karimova');
  await page.fill('[name=phone]', '+998 90 123-45-67');
  await page.fill('[name=address]', 'Tashkent, Amir Temur 12, kv 4');
  await page.click('#co-form button[type=submit]');
  await page.waitForSelector('#screen-order.active', { timeout: 60000 });
  return (await page.textContent('#or-ref')).trim();
}

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 950 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  const ref = await placeOrder(page);
  console.log('0. a customer ordered', ref);

  // sign in
  await page.goto(`${BASE}/admin/`);
  await page.fill('#login-token', TOKEN);
  await page.click('#login-form button[type=submit]');
  await page.waitForSelector('#screen-main.active', { timeout: 15000 });
  console.log('1. orders is the tab you land on:',
    await page.isVisible('#tab-orders') && !await page.isVisible('#tab-designs'));

  // 2. the order is in the open list
  await page.waitForSelector(`.order-row[data-ref="${ref}"]`, { timeout: 20000 });
  const row = await page.$eval(`.order-row[data-ref="${ref}"]`,
    (el) => el.innerText.replace(/\n/g, ' | '));
  console.log('2. in the open list:', JSON.stringify(row));

  // 3. search finds it by phone, punctuation and all. Other runs may have
  //    left orders with the same phone, so what matters is that this one is
  //    found and that a search which should match nothing matches nothing.
  await page.fill('#o-search', '901234567');
  await page.waitForSelector(`.order-row[data-ref="${ref}"]`, { timeout: 20000 });
  console.log('3. found by phone digits alone: true');

  await page.fill('#o-search', 'ZZ-NOTHING');
  await page.waitForFunction(
    () => document.querySelectorAll('.order-row').length === 0,
    undefined, { timeout: 20000 });
  console.log('   a search that should match nothing matches nothing: true');

  await page.fill('#o-search', '');
  await page.waitForSelector(`.order-row[data-ref="${ref}"]`);

  // 4. the detail screen
  await page.click(`.order-row[data-ref="${ref}"]`);
  await page.waitForSelector('#order-detail:not(.hidden)');
  console.log('4. status:', JSON.stringify(await page.textContent('#od-status')));
  console.log('   customer:', JSON.stringify(await page.textContent('#od-name')),
    '| address:', JSON.stringify(await page.textContent('#od-address')));
  console.log('   amount:', JSON.stringify(await page.textContent('#od-amount')),
    '| book:', JSON.stringify(await page.textContent('#od-book')));
  const alerted = await page.isVisible('#od-alert');
  console.log('   tells you what it is waiting for:', alerted);
  if (!alerted) throw new Error('no guidance on a pending order');

  const noFiles = await page.$$eval('#od-files a', (els) => els.length);
  console.log('   print files before payment:', noFiles);
  if (noFiles !== 0) throw new Error('print files existed before payment');
  await page.screenshot({ path: SHOTS + '/99-orders-pending.png' });

  // 5. confirm the transfer — the daily action
  await page.fill('#od-note', 'transfer seen 12:04');
  await page.click('#od-actions button.primary');
  await page.waitForFunction(
    () => document.querySelectorAll('#od-files a').length === 2,
    undefined, { timeout: 180000 });
  console.log('5. after confirming ->',
    JSON.stringify(await page.textContent('#od-status')));
  const files = await page.$$eval('#od-files a', (els) => els.map((e) => e.textContent));
  console.log('   print files:', files.join(' | '));

  // the link actually serves a PDF
  const href = await page.$eval('#od-files a', (el) => el.href);
  const served = await page.evaluate(async (u) => {
    const r = await fetch(u);
    const head = new Uint8Array(await (await r.blob()).slice(0, 5).arrayBuffer());
    return { status: r.status, magic: String.fromCharCode(...head) };
  }, href);
  console.log('   the interior link serves:', JSON.stringify(served));
  if (served.status !== 200 || !served.magic.startsWith('%PDF')) {
    throw new Error('the print link did not serve a PDF');
  }

  // the note was recorded
  const history = await page.$eval('#od-events', (el) => el.innerText);
  console.log('   note kept in the history:', history.includes('transfer seen 12:04'));
  if (!history.includes('transfer seen 12:04')) throw new Error('note not recorded');

  // 6. confirming again must not render again
  const before = await page.$$eval('#od-events li', (els) => els.length);
  await page.click(`.order-row[data-ref="${ref}"]`);
  await page.waitForSelector('#order-detail:not(.hidden)');
  const stillPrimary = await page.$('#od-actions button.primary');
  console.log('6. "mark paid" is gone once paid:', stillPrimary === null);
  if (stillPrimary) throw new Error('a paid order still offers "mark paid"');
  const after = await page.$$eval('#od-events li', (els) => els.length);
  if (after !== before) throw new Error('reopening changed the history');

  // 7. the fulfilment path, driven by what the server says is possible
  for (const [label, expect] of [
    ['Sent to the printer', 'At the printer'],
    ['Shipped', 'Shipped'],
    ['Delivered', 'Delivered'],
  ]) {
    await page.click(`#od-actions button:text-is("${label}")`);
    await page.waitForFunction(
      (want) => document.getElementById('od-status').textContent.trim() === want,
      expect, { timeout: 20000 });
    console.log(`7. ${label.padEnd(22)} -> ${expect}`);
  }
  await page.screenshot({ path: SHOTS + '/99-orders-delivered.png' });

  // 8. a finished order offers nothing, and leaves the open list
  const actions = await page.$eval('#od-actions', (el) => el.innerText.trim());
  console.log('8. a delivered order offers:', JSON.stringify(actions));
  await page.click('#btn-orders-refresh');
  await page.waitForFunction(
    (r) => !document.querySelector(`.order-row[data-ref="${r}"]`), ref,
    { timeout: 20000 });
  console.log('   gone from the open list: true');
  await page.selectOption('#o-status', '');
  await page.waitForSelector(`.order-row[data-ref="${ref}"]`, { timeout: 20000 });
  console.log('   still findable under All: true');

  // 9. the designs tab still works
  await page.click('.tab[data-tab="designs"]');
  await page.waitForSelector('#tab-designs:not(.hidden)');
  console.log('9. switching to cover designs still works: true');

  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) throw new Error('page errors');
  console.log('ORDERS ADMIN CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
