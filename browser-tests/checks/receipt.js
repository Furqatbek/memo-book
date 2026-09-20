/* A100: the customer attaches proof of their transfer.
 *
 * In the card-transfer pilot nobody tells us a payment arrived — the
 * operator matches transfers against the bank by hand. The receipt is the
 * one piece of evidence only the customer has, so it belongs under the bank
 * card, at the moment they have just been asked to send money.
 *
 * Note where this lives: the ORDER screen, not the checkout form. At
 * checkout the customer has not seen the card or the amount yet, so there is
 * nothing for them to have a receipt of.
 *
 * Needs ADMIN_TOKEN=dev-admin for the last part, which checks the operator
 * actually gets a link to open.
 *
 *   node checks/receipt.js
 */
const { chromium } = require('playwright');
const path = require('path');
const BASE = 'http://127.0.0.1:8000';
const TOKEN = 'dev-admin';
const SHOTS = path.join(__dirname, '..', 'shots');
// A 16-sheet book is 32 pages, and checkout refuses a book with holes in
// it — so this fills the whole thing.
const PHOTOS = Array.from({ length: 32 }, (_, i) =>
  path.join(__dirname, '..', 'fixtures', `photo${String(i % 16).padStart(2, '0')}.jpg`));

const PNG = Buffer.concat([
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  Buffer.alloc(400)]);
const TOO_BIG = Buffer.concat([
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  Buffer.alloc(2 * 1024 * 1024 + 1)]);
const NOT_AN_IMAGE = Buffer.from('<html><script>alert(1)</script></html>');

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

const attach = (page, name, mimeType, buffer) =>
  page.setInputFiles('#receipt-input', { name, mimeType, buffer });

(async () => {
  require('fs').mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 950 } })).newPage();
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e)));

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
  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('32 '),
    undefined, { timeout: 180000 });
  await page.click('#btn-autofill');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 60000 });

  await page.click('#btn-preview');
  await page.waitForSelector('#screen-preview.active', { timeout: 30000 });
  await page.waitForFunction(
    () => document.querySelectorAll('#pv-grid figure').length > 0,
    undefined, { timeout: 240000 });
  await page.check('#pv-confirm');
  await page.waitForSelector('#pv-checkout:not([disabled])', { timeout: 30000 });
  await page.click('#pv-checkout');
  await page.waitForSelector('#screen-checkout.active', { timeout: 30000 });
  await page.fill('[name=name]', 'Receipt Probe');
  await page.fill('[name=phone]', '+998 90 111 22 33');
  await page.fill('[name=address]', 'Tashkent, probe 2');
  // Catch the response: if checkout is refused the order screen never
  // arrives, and a bare timeout says nothing about why.
  const checkout = page.waitForResponse(
    (r) => r.url().includes('/checkout') && r.request().method() === 'POST',
    { timeout: 30000 });
  await page.click('#co-form button[type=submit]');
  const co = await checkout;
  if (!co.ok()) {
    const body = await co.json().catch(() => ({}));
    throw new Error(`checkout refused: HTTP ${co.status()} `
      + `${JSON.stringify(body.error || body)}`);
  }
  await page.waitForSelector('#screen-order.active', { timeout: 60000 });

  console.log('THE BOX IS WHERE THE MONEY IS ASKED FOR');
  await page.waitForSelector('#or-receipt:not(.hidden)', { timeout: 30000 });
  check('the receipt box is on the order screen', true);
  check('it is not on the checkout form',
    await page.$('#screen-checkout #receipt-input') === null);
  check('nothing says a receipt arrived yet',
    await page.isHidden('#receipt-done'));
  await page.screenshot({ path: `${SHOTS}/100-receipt-empty.png` });

  console.log('A FILE THAT IS NOT WHAT IT CLAIMS IS REFUSED');
  // A browser will happily send image/png for a file of HTML, and these
  // objects are served from our own storage hostname.
  await attach(page, 'receipt.png', 'image/png', NOT_AN_IMAGE);
  await page.waitForSelector('#receipt-error:not(.hidden)', { timeout: 30000 });
  check('an HTML file named .png is refused',
    await page.isHidden('#receipt-done'),
    JSON.stringify((await page.textContent('#receipt-error')).slice(0, 60)));

  console.log('AND SO IS ONE OVER 2 MB');
  await attach(page, 'huge.png', 'image/png', TOO_BIG);
  await page.waitForSelector('#receipt-error:not(.hidden)', { timeout: 30000 });
  const tooBig = await page.textContent('#receipt-error');
  check('a 2 MB+ file is refused with a reason', /2 MB|2 МБ/i.test(tooBig),
    JSON.stringify(tooBig.slice(0, 60)));
  check('and still nothing is recorded', await page.isHidden('#receipt-done'));

  console.log('A REAL ONE IS ACCEPTED');
  await attach(page, 'receipt.png', 'image/png', PNG);
  await page.waitForSelector('#receipt-done:not(.hidden)', { timeout: 30000 });
  check('the customer is told it arrived', true,
    JSON.stringify((await page.textContent('#receipt-done')).slice(0, 40)));
  check('the button now offers to replace it',
    /replace/i.test(await page.textContent('#receipt-pick-label')));
  await page.screenshot({ path: `${SHOTS}/100-receipt-done.png` });

  const ref = await page.textContent('#or-ref');
  console.log('AND THE OPERATOR CAN OPEN IT');
  const detail = await (await fetch(
    `${BASE}/api/v1/admin/orders/${ref.trim()}`,
    { headers: { 'X-Admin-Token': TOKEN } })).json();
  check('the console detail carries the receipt', !!(detail.receipt
    && detail.receipt.url), JSON.stringify(detail.receipt
      && detail.receipt.content_type));
  if (detail.receipt) {
    const served = await fetch(detail.receipt.url);
    check('and the link serves the file back', served.status === 200
      && served.headers.get('content-type') === 'image/png',
      `${served.status} ${served.headers.get('content-type')}`);
  }

  console.log('errors:', errs.length ? errs : 'none');
  await browser.close();
  if (errs.length || failed) {
    console.error(`RECEIPT CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('RECEIPT CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
