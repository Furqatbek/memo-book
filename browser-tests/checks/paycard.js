const { chromium } = require('playwright');
const path = require('path');
const SHOTS = path.join(__dirname, '..', 'shots');
const PHOTOS = Array.from({ length: 32 }, (_, i) =>
  path.join(__dirname, '..', 'fixtures', `photo${String(i % 16).padStart(2, '0')}.jpg`));
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 850 } });
  await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'http://127.0.0.1:8000' });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto('http://127.0.0.1:8000/editor/');
  await page.click('.btype[data-btype=\"memory\"]');
  await page.click('.tier[data-tier="16"]');
  // A71 put a cover-design gallery between size and editor.
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');

  // item 3: no placeholder hint on blank cover/page
  if (await page.$('.canvas-empty')) throw new Error('canvas-empty still rendered');
  await page.click('#filmstrip .film-item:nth-child(2)');
  if (await page.$('.canvas-empty')) throw new Error('canvas-empty on page 1');
  console.log('canvas placeholder text gone: ok');

  // fill the book, order it
  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('32 '), undefined,
    { timeout: 120000 });
  await page.click('#btn-autofill');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'), undefined,
    { timeout: 30000 });
  await page.click('#btn-preview');
  await page.waitForFunction(
    () => document.querySelectorAll('#pv-grid figure').length >= 32, undefined,
    { timeout: 120000 });
  await page.check('#pv-confirm');
  await page.waitForSelector('#pv-checkout:not([disabled])', { timeout: 30000 });
  await page.click('#pv-checkout');
  await page.waitForSelector('#screen-checkout.active');
  await page.fill('[name=name]', 'Pay Card Test');
  await page.fill('[name=phone]', '+998901234567');
  await page.fill('[name=address]', 'Tashkent, test street 1');
  // If checkout is refused, the order screen never arrives and the timeout
  // says nothing about why. Catch the response so a failure names its cause.
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
  await page.waitForSelector('#screen-order.active', { timeout: 30000 });

  // item 4: bank card appears with formatted number + holder
  await page.waitForSelector('#or-paycard:not(.hidden)', { timeout: 15000 });
  const num = await page.$eval('#pay-number', (el) => el.textContent);
  const holder = await page.$eval('#pay-holder', (el) => el.textContent);
  console.log('card number shown:', JSON.stringify(num), '| holder:', JSON.stringify(holder));
  if (num !== '8600 1234 5678 9012' || holder !== 'FURQATBEK TESTOV') {
    throw new Error('card details wrong');
  }
  const noteHidden = await page.$eval('#or-pay-note', (el) => el.classList.contains('hidden'));
  console.log('generic pay note hidden while card shown:', noteHidden);

  // copy button puts bare digits on the clipboard
  await page.click('#pay-copy');
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  console.log('clipboard:', JSON.stringify(copied));
  if (copied !== '8600123456789012') throw new Error('copy failed');
  await page.screenshot({ path: SHOTS + '/72-pay-card.png' });

  // The transfer is verified by a human, so the card stays on screen through
  // paid/rendering/rendered — it goes only once the operator sends the order
  // to production (A54). With AUTO_CONFIRM_ORDERS the order never waits for
  // payment at all, so the dev-pay button is hidden and there is nothing to
  // click.
  const devPay = await page.$eval('#or-dev',
    (el) => !el.classList.contains('hidden'));
  console.log('dev simulate-payment offered:', devPay);
  if (devPay) {
    page.once('dialog', (d) => d.accept());
    await page.click('#or-dev-pay');
  }
  await page.waitForFunction(
    () => document.querySelectorAll('#or-timeline li.done').length >= 2,
    undefined, { timeout: 60000 });
  const stillShown = await page.$eval('#or-paycard',
    (el) => !el.classList.contains('hidden'));
  const status = await page.$eval('#or-timeline li.now', (el) => el.textContent.trim());
  console.log('after payment ->', JSON.stringify(status),
              '| card still shown:', stillShown);
  if (!stillShown) throw new Error('card vanished before the operator confirmed');

  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) throw new Error('page errors');
  console.log('PAY CARD CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
