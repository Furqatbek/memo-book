/* Walk the flow and screenshot every screen in scope, desktop + mobile.
 * Not a check — a way to look at what we are changing.
 *   node checks/shots.js [before|after]
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const BASE = 'http://127.0.0.1:8000';
const TAG = process.argv[2] || 'now';
const OUT = path.join(__dirname, '..', 'shots', TAG);
const TOKEN = 'dev-admin';
const ART = path.join(__dirname, '..', 'fixtures', 'artwork-hearts.png');
const PHOTOS = Array.from({ length: 32 }, (_, i) =>
  path.join(__dirname, '..', 'fixtures', `photo${String(i % 16).padStart(2, '0')}.jpg`));

async function seedDesign() {
  const form = new FormData();
  form.append('slug', 'shots-gold');
  form.append('name', 'Gold hearts');
  form.append('book_types', 'love,travel,birthday,memory');
  form.append('bg_color', '#7a2740');
  form.append('photo_rect', '{"x_mm":19,"y_mm":24,"w_mm":110,"h_mm":110}');
  form.append('title', '{"x_mm":74,"y_mm":170,"size_pt":24}');
  form.append('artwork', new Blob([fs.readFileSync(ART)], { type: 'image/png' }), 'a.png');
  await fetch(`${BASE}/api/v1/admin/cover-designs`,
    { method: 'POST', headers: { 'X-Admin-Token': TOKEN }, body: form });
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  await seedDesign();
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });

  for (const [device, viewport] of [['desktop', { width: 1280, height: 900 }],
                                    ['mobile', { width: 390, height: 844 }]]) {
    const page = await (await browser.newContext({ viewport })).newPage();
    const shot = (n) => page.screenshot({ path: `${OUT}/${device}-${n}.png` });

    await page.goto(`${BASE}/editor/`);
    await page.evaluate(() => localStorage.clear());
    await page.goto(`${BASE}/editor/`);
    await page.waitForTimeout(700);
    await shot('1-type');

    await page.click('.btype[data-btype="travel"]');
    await page.waitForFunction(() => document.querySelector('[data-tier-pages]').textContent,
      undefined, { timeout: 10000 });
    await page.waitForTimeout(300);
    await shot('2-size');

    await page.click('.tier[data-tier="16"]');
    await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
    if (await page.isVisible('#design-step')) {
      await page.waitForTimeout(600);
      await shot('3-cover');
      await page.click('#design-skip');
    }
    await page.waitForSelector('#screen-editor.active');

    // straight to preview with a full book
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
      () => document.querySelectorAll('#pv-grid figure').length >= 8,
      undefined, { timeout: 180000 });
    await page.waitForTimeout(500);
    await shot('4-preview');

    await page.check('#pv-confirm');
    await page.waitForSelector('#pv-checkout:not([disabled])', { timeout: 30000 });
    await page.click('#pv-checkout');
    await page.waitForSelector('#screen-checkout.active');
    await page.waitForTimeout(300);
    await shot('5-checkout');

    await page.fill('[name=name]', 'Aziza Karimova');
    await page.fill('[name=phone]', '+998901234567');
    await page.fill('[name=address]', 'Tashkent, Chilonzor 5, dom 12, kv 34');
    await page.click('#co-form button[type=submit]');
    await page.waitForSelector('#screen-order.active', { timeout: 240000 });
    await page.waitForTimeout(1200);
    await shot('6-order');
    await page.close();
  }

  await browser.close();
  console.log('shots in', OUT);
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
