const { chromium } = require('playwright');
const path = require('path');
const SHOTS = path.join(__dirname, '..', 'shots');
const PHOTOS = Array.from({ length: 32 }, (_, i) =>
  path.join(__dirname, '..', 'fixtures', `photo${String(i % 16).padStart(2, '0')}.jpg`));
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 1360, height: 850 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('response', async (r) => {
    if (r.url().includes('/checkout') || (r.status() >= 400 && r.url().includes('/api/'))) {
      let body = '';
      try { body = (await r.text()).slice(0, 300); } catch (e) { /* stream gone */ }
      console.log(`[net] ${r.status()} ${r.request().method()} ${r.url().split('/api/')[1] || r.url()} ${body}`);
    }
  });
  await page.goto('http://127.0.0.1:8000/editor/');
  await page.click('.btype[data-btype="memory"]');
  await page.click('.tier[data-tier="16"]');
  // A71 put a cover-design gallery between size and editor.
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');
  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('32 '), undefined,
    { timeout: 120000 });
  await page.click('#btn-autofill');
  // wait for the auto-place result to be adopted, not just for "saved"
  await page.waitForFunction(
    () => document.querySelectorAll('#filmstrip .film-item img').length >= 32, undefined,
    { timeout: 30000 });
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'), undefined,
    { timeout: 30000 });
  await page.click('#btn-preview');
  await page.waitForFunction(
    () => document.querySelectorAll('#pv-grid figure').length >= 32, undefined,
    { timeout: 120000 });

  // checkout screen shows the highlighted card-transfer hint
  await page.check('#pv-confirm');
  await page.waitForSelector('#pv-checkout:not([disabled])');
  await page.click('#pv-checkout');
  await page.waitForSelector('#screen-checkout.active');
  const hint = await page.$eval('#co-form .pay-hint', (el) => el.textContent);
  console.log('checkout hint:', JSON.stringify(hint.slice(0, 50) + '...'));
  if (!hint.includes('card')) throw new Error('checkout pay hint missing');

  await page.fill('[name=name]', 'Auto Flow Test');
  await page.fill('[name=phone]', '+998901234567');
  await page.fill('[name=address]', 'Tashkent, test street 1');
  await page.click('#co-form button[type=submit]');
  await page.waitForSelector('#screen-order.active', { timeout: 60000 });

  // trust-first: order proceeds immediately — timeline past "awaiting payment"
  await page.waitForFunction(() => {
    const done = document.querySelectorAll('#or-timeline li.done').length;
    const now = document.querySelector('#or-timeline li.now');
    return done >= 2 && now; // paid + preparing done/underway
  }, undefined, { timeout: 60000 });
  const timeline = await page.$$eval('#or-timeline li', (els) =>
    els.map((el) => `${el.className || '-'}:${el.textContent}`).slice(0, 4));
  console.log('timeline:', timeline);

  // card block visible with highlighted note; simulate button hidden? In the
  // dev environment devConfig answers so the button WOULD show for pending —
  // but the order is never pending here, so it must be hidden.
  await page.waitForSelector('#or-paycard:not(.hidden)', { timeout: 15000 });
  const note = await page.$eval('#or-paycard .pay-note', (el) => el.textContent);
  console.log('card note:', JSON.stringify(note.slice(0, 60) + '...'));
  if (!note.includes('already being prepared')) throw new Error('note not the trust-first text');
  const devHidden = await page.$eval('#or-dev', (el) => el.classList.contains('hidden'));
  console.log('simulate button hidden:', devHidden);
  if (!devHidden) throw new Error('simulate button visible in auto flow');

  // flow really went on: PDFs exist (dev artifacts card appears when rendered)
  await page.waitForSelector('#or-files:not(.hidden)', { timeout: 120000 });
  console.log('print files ready without any payment action: true');
  const bg = await page.$eval('#or-paycard', (el) => getComputedStyle(el).backgroundColor);
  console.log('card block highlight bg:', bg);
  await page.screenshot({ path: SHOTS + '/77-auto-flow.png' });

  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) throw new Error('page errors');
  console.log('AUTO FLOW CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
