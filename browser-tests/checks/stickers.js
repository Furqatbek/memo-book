const { chromium } = require('playwright');
const path = require('path');
const SHOTS = path.join(__dirname, '..', 'shots');
const PHOTOS = [path.join(__dirname, '..', 'fixtures', 'photo00.jpg')];
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 1360, height: 850 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto('http://127.0.0.1:8000/editor/');
  await page.click('.btype[data-btype="travel"]');
  await page.click('.tier[data-tier="16"]');
  // A71 put a cover-design gallery between size and editor.
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');

  // --- picker opens on flags for a travel book ---
  await page.click('#btn-add-sticker');
  await page.waitForSelector('#tray-stickers:not(.hidden)');
  const activeTab = await page.$eval('.sp-tab.active', (el) => el.textContent);
  const itemCount = await page.$$eval('.sp-item', (els) => els.length);
  console.log('default tab:', activeTab, '| items in tab:', itemCount);
  if (itemCount !== 41) throw new Error('flags tab should hold 41 flags');

  // --- add the Uzbekistan flag to the COVER (current page = cover) ---
  await page.click('.sp-item img[src*="flag-uz"]');
  await page.waitForSelector('.sticker[data-id]');
  console.log('flag sticker on cover: ok');

  // --- drag it ---
  const before = await page.$eval('.sticker', (el) => el.getBoundingClientRect().x);
  const box = await (await page.$('.sticker')).boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 - 80, box.y + box.height / 2 - 60, { steps: 5 });
  await page.mouse.up();
  const after = await page.$eval('.sticker', (el) => el.getBoundingClientRect().x);
  console.log('drag moved sticker:', Math.round(before - after), 'px');
  if (Math.abs(before - after) < 40) throw new Error('drag did not move sticker');

  // --- add a map to page 1, switch tab ---
  await page.click('#filmstrip .film-item:nth-child(2)');
  await page.click('#btn-add-sticker');
  await page.click('.sp-tab:nth-child(2)');   // maps
  await page.click('.sp-item img[src*="map-uz"]');
  await page.waitForSelector('.sticker[data-id]');
  console.log('map sticker on page 1: ok');

  // --- delete via toolbar works ---
  await page.click('#btn-add-sticker');
  await page.click('.sp-tab:nth-child(3)');   // travel pack
  await page.click('.sp-item img[src*="airplane"]');
  await page.waitForFunction(() => document.querySelectorAll('.sticker').length === 2);
  await page.click('#sel-toolbar .btn.danger');
  await page.waitForFunction(() => document.querySelectorAll('.sticker').length === 1);
  console.log('sticker delete: ok');

  // --- server roundtrip ---
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'), undefined,
    { timeout: 30000 });
  const creds = await page.evaluate(() => JSON.parse(localStorage.getItem('mb-book')));
  const book = await (await fetch(`http://127.0.0.1:8000/api/v1/books/${creds.book_id}`,
    { headers: { 'X-Edit-Token': creds.edit_token } })).json();
  console.log('server cover stickers:', JSON.stringify(book.layout.cover.stickers));
  console.log('server page-1 stickers:', JSON.stringify(book.layout.pages[0].stickers));
  if (book.layout.cover.stickers[0].sticker_id !== 'flag-uz'
      || book.layout.pages[0].stickers[0].sticker_id !== 'map-uz') {
    throw new Error('stickers not persisted');
  }

  // --- reload survives ---
  await page.reload();
  await page.click('#btn-resume');
  await page.waitForSelector('#screen-editor.active');
  await page.waitForSelector('.sticker[data-id]', { timeout: 10000 });
  console.log('stickers survive reload: ok');
  await page.screenshot({ path: SHOTS + '/79-stickers.png' });

  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) throw new Error('page errors');
  console.log('STICKERS CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
