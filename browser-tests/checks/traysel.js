const { chromium } = require('playwright');
const path = require('path');
const SHOTS = path.join(__dirname, '..', 'shots');
const fs = require('fs');
const PHOTOS = Array.from({ length: 4 }, (_, i) =>
  path.join(__dirname, '..', 'fixtures', `photo${String(i).padStart(2, '0')}.jpg`));
const EMPTY = path.join(__dirname, '..', 'fixtures', 'empty.jpg');
fs.writeFileSync(EMPTY, Buffer.alloc(0)); // zero-byte -> job fails client-side
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 1360, height: 850 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto('http://127.0.0.1:8000/editor/');
  await page.click('.btype[data-btype=\"memory\"]');
  await page.click('.tier[data-tier="16"]');
  // A71 put a cover-design gallery between size and editor.
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');

  // --- failed-job dismissal ---
  await page.setInputFiles('#file-input', [EMPTY]);
  await page.waitForSelector('#tray-grid .ph-card.failed .ph-del', { timeout: 10000 });
  await page.click('#tray-grid .ph-card.failed .ph-del');
  await page.waitForFunction(
    () => !document.querySelector('#tray-grid .ph-card.failed'), undefined, { timeout: 5000 });
  console.log('failed-card dismissed: ok');

  // --- real uploads ---
  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('4 '),
    { timeout: 60000 });

  // dimension tooltip on cards
  const title = await page.$eval('#tray-grid .ph-card', (el) => el.title);
  console.log('card tooltip:', JSON.stringify(title));
  if (!/^\d+×\d+ px$/.test(title)) throw new Error('tooltip missing dims');

  // --- select mode: pick 2, delete ---
  const selHidden = await page.$eval('#btn-select-mode', (el) => el.classList.contains('hidden'));
  if (selHidden) throw new Error('select button hidden with photos present');
  await page.click('#btn-select-mode');
  await page.waitForSelector('#btn-delete-sel:not(.hidden)');
  console.log('delete-sel label (0):',
    await page.$eval('#btn-delete-sel', (el) => `${el.textContent} disabled=${el.disabled}`));
  await page.click('#tray-grid .ph-card:nth-child(1)');
  await page.click('#tray-grid .ph-card:nth-child(2)');
  const picked = await page.$$eval('#tray-grid .ph-card.picked', (els) => els.length);
  console.log('picked cards:', picked);
  const label = await page.$eval('#btn-delete-sel', (el) => el.textContent);
  console.log('delete-sel label (2):', JSON.stringify(label));
  if (picked !== 2 || !label.includes('2')) throw new Error('selection state wrong');
  // clicking a picked card in select mode must NOT place it
  const placementsNow = await page.$$eval('#page-canvas .pl', (els) => els.length);
  if (placementsNow !== 0) throw new Error('select-mode click placed a photo');
  page.once('dialog', (d) => d.accept());
  await page.click('#btn-delete-sel');
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('2 '),
    { timeout: 30000 });
  const stillSelecting = await page.$eval('#btn-select-mode', (el) => el.classList.contains('active'));
  console.log('select mode exited after delete:', !stillSelecting);

  // --- delete-all still works, and select buttons hide at zero ---
  page.once('dialog', (d) => d.accept());
  await page.click('#btn-delete-all');
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('0 '),
    { timeout: 30000 });
  const hiddenAfter = await page.$eval('#btn-select-mode', (el) => el.classList.contains('hidden'));
  console.log('select hidden at 0 photos:', hiddenAfter);
  await page.screenshot({ path: SHOTS + '/70-tray-select.png' });
  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) throw new Error('page errors');
  console.log('TRAY SELECT CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
