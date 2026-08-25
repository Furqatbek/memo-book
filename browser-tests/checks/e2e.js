/* End-to-end editor test against the local devserver:
   start -> create a 16-SHEET (32-page) book -> upload 32 photos -> auto-fill -> add text ->
   preview -> checkout -> dev payment -> order rendered. */
const { chromium } = require('playwright');
const path = require('path');

const BASE = 'http://127.0.0.1:8000/editor/';
const PHOTOS = Array.from({ length: 32 }, (_, i) =>
  path.join(__dirname, '..', 'fixtures', `photo${String(i % 16).padStart(2, '0')}.jpg`));
const SHOT = (name) => path.join(__dirname, '..', 'shots', name);

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 1360, height: 850 } });
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));

  await page.goto(BASE);
  await page.waitForSelector('.btype:not([disabled])', { timeout: 10000 });
  await page.screenshot({ path: SHOT('01-start.png') });

  // 1. Create a 16-sheet (32-page) book
  await page.click('.btype[data-btype=\"memory\"]');
  await page.waitForSelector('.tier:not([disabled])', { timeout: 10000 });
  await page.click('.tier[data-tier="16"]');
  // A71 put a cover-design gallery between size and editor.
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active', { timeout: 10000 });
  await page.screenshot({ path: SHOT('02-editor-empty.png') });

  // 2. Upload 32 photos, wait for ingest
  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('32 '),
    { timeout: 120000 });
  console.log('uploads ready:', await page.textContent('#tray-count'));
  await page.screenshot({ path: SHOT('03-photos-uploaded.png') });

  // 3. Auto-fill
  await page.click('#btn-autofill');
  await page.waitForFunction(
    () => document.querySelectorAll('#filmstrip .film-item.empty').length === 0,
    { timeout: 30000 });
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    { timeout: 30000 });
  await page.screenshot({ path: SHOT('04-autofilled.png') });

  // 4. Go to page 1, add a text box, type
  await page.click('#filmstrip .film-item:nth-child(2)');
  await page.click('#btn-add-text');
  await page.click('.textbox .textbox-content');
  await page.keyboard.type('Samarkand, June 2026');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    { timeout: 30000 });
  await page.screenshot({ path: SHOT('05-text-added.png') });

  // 5. Set a cover photo + title
  await page.click('#filmstrip .film-item:first-child');
  await page.click('#tray-grid .ph-card:first-child');
  await page.fill('.cover-title', 'Our Trip');
  await page.fill('.cover-subtitle', 'Uzbekistan 2026');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    { timeout: 30000 });
  await page.screenshot({ path: SHOT('06-cover.png') });

  // 6. Preview
  await page.click('#btn-preview');
  await page.waitForFunction(
    () => document.querySelectorAll('.pv-page img').length === 33
      && document.querySelector('.pv-cover'),
    { timeout: 180000 });
  await page.screenshot({ path: SHOT('07-preview.png') });

  // 7. Confirm + checkout
  await page.check('#pv-confirm');
  await page.click('#pv-checkout');
  await page.waitForSelector('#screen-checkout.active');
  await page.fill('input[name=name]', 'Aziza Karimova');
  await page.fill('input[name=phone]', '+998 90 123 45 67');
  await page.fill('textarea[name=address]', 'Tashkent, Chilonzor 5, dom 12, kv 34');
  await page.screenshot({ path: SHOT('08-checkout.png') });
  await page.click('#co-form button[type=submit]');
  await page.waitForSelector('#or-details:not(.hidden)', { timeout: 60000 });
  const ref = await page.textContent('#or-ref');
  const amount = await page.textContent('#or-amount');
  console.log('order created:', ref, '|', amount);
  await page.screenshot({ path: SHOT('09-order-pending.png') });

  // 8. Simulate the dev payment — one click, no prompt (the editor fetches
  //    the signature from /payments/dev/config in dev environments).
  const devPay = await page.$eval('#or-dev',
    (el) => !el.classList.contains('hidden'));
  if (devPay) {
    page.once('dialog', (d) => { d.dismiss(); throw new Error('unexpected prompt'); });
    await page.click('#or-dev-pay');
  }
  await page.waitForFunction(() => {
    const now = document.querySelector('#or-timeline li.now');
    return now && !now.textContent.includes('payment') &&
           document.querySelectorAll('#or-timeline li.done').length >= 3;
  }, { timeout: 300000 });
  const status = await page.textContent('#or-timeline li.now');
  console.log('order status now:', status.trim());
  await page.waitForSelector('#or-files:not(.hidden)', { timeout: 30000 });
  const interiorHref = await page.getAttribute('#or-file-interior', 'href');
  const pdfResp = await fetch(interiorHref);
  const head = Buffer.from(await pdfResp.arrayBuffer()).subarray(0, 5).toString();
  console.log('interior link serves:', pdfResp.status, head);
  if (head !== '%PDF-') throw new Error('interior link did not serve a PDF');
  await page.screenshot({ path: SHOT('10-order-paid.png') });

  // 9. Reload -> resume flow shows the stored book/locked state
  await page.goto(BASE);
  await page.waitForSelector('#resume-card:not(.hidden)', { timeout: 10000 });
  await page.screenshot({ path: SHOT('11-resume.png') });

  // 10. Mobile viewport sanity (fresh context — starts its own book)
  const mob = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await mob.goto(BASE);
  await mob.waitForSelector('.btype:not([disabled])', { timeout: 10000 });
  await mob.screenshot({ path: SHOT('12-mobile-start.png') });
  await mob.click('.btype[data-btype="memory"]');
  await mob.waitForSelector('.tier:not([disabled])', { timeout: 10000 });
  await mob.click('.tier[data-tier="16"]');
  // A71 put a cover-design gallery between size and editor.
  await mob.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await mob.isVisible('#design-step')) await mob.click('#design-skip');
  await mob.waitForSelector('#screen-editor.active', { timeout: 15000 });
  await mob.setInputFiles('#file-input', PHOTOS.slice(0, 3));
  await mob.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('3 '),
    { timeout: 60000 });
  await mob.click('#tray-grid .ph-card:first-child');  // becomes the cover photo
  await mob.waitForTimeout(800);
  await mob.screenshot({ path: SHOT('13-mobile-editor.png') });

  console.log('console errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) process.exit(2);
  console.log('E2E PASSED');
})().catch((e) => { console.error('E2E FAILED:', e); process.exit(1); });
