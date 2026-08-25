const { chromium } = require('playwright');
const path = require('path');
const SHOTS = path.join(__dirname, '..', 'shots');
const PHOTOS = Array.from({ length: 16 }, (_, i) =>
  path.join(__dirname, '..', 'fixtures', `photo${String(i % 8).padStart(2, '0')}.jpg`));
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 1360, height: 850 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto('http://127.0.0.1:8000/editor/');

  // tier cards show .env prices
  await page.waitForFunction(
    () => document.querySelector('[data-tier-price="16"]').textContent.length > 0, undefined,
    { timeout: 10000 });
  const p16 = await page.$eval('[data-tier-price="16"]', (el) => el.textContent);
  const p96 = await page.$eval('[data-tier-price="96"]', (el) => el.textContent);
  console.log('tier prices:', JSON.stringify(p16), JSON.stringify(p96));
  if (!p16.replace(/\s/g,' ').includes('299 000') || !p96.replace(/\s/g,' ').includes('799 000')) throw new Error('tier price wrong');
  await page.screenshot({ path: SHOTS + '/73-tier-prices.png' });

  // preview footer shows the amount for the chosen tier
  await page.click('.btype[data-btype=\"memory\"]');
  await page.click('.tier[data-tier="16"]');
  // A71 put a cover-design gallery between size and editor.
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');
  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('16 '), undefined,
    { timeout: 120000 });
  await page.click('#btn-autofill');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'), undefined,
    { timeout: 30000 });
  await page.click('#btn-preview');
  await page.waitForFunction(
    () => document.getElementById('pv-price').textContent.length > 0, undefined,
    { timeout: 15000 });
  const pv = await page.$eval('#pv-price', (el) => el.textContent);
  console.log('preview footer price:', JSON.stringify(pv));
  if (!pv.replace(/\s/g,' ').includes('299 000')) throw new Error('preview price wrong');

  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) throw new Error('page errors');
  console.log('PRICES CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
