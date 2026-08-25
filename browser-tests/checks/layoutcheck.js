/* Does the SHIPPED code actually do layouts + snapping? Decides whether the
   production report is a code bug or a stale-cache problem. */
const { chromium } = require('playwright');
const path = require('path');
const SHOTS = path.join(__dirname, '..', 'shots');
const PHOTOS = Array.from({ length: 4 }, (_, i) =>
  path.join(__dirname, '..', 'fixtures', `photo${String(i).padStart(2, '0')}.jpg`));
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 1360, height: 850 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto('http://127.0.0.1:8000/editor/');
  await page.click('.btype[data-btype="memory"]');
  await page.click('.tier[data-tier="16"]');
  // A71 put a cover-design gallery between size and editor.
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');

  // 1. button label translated?
  const label = await page.$eval('#btn-layout', (el) => el.textContent.trim());
  console.log('1. layout button label:', JSON.stringify(label));
  if (!label || label === 'tool.layout') throw new Error('layout button untranslated');

  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('4 '), undefined,
    { timeout: 90000 });

  // go to page 1 (layout button is hidden on the cover)
  await page.click('#filmstrip .film-item:nth-child(2)');
  const hidden = await page.$eval('#btn-layout', (el) => el.classList.contains('hidden'));
  console.log('   layout button visible on a page:', !hidden);

  // 2. layout button opens the picker
  await page.click('#btn-layout');
  const popped = await page.$('.layout-pop');
  console.log('2. layout picker opens:', !!popped);
  if (!popped) throw new Error('layout picker did not open');
  const options = await page.$$eval('.layout-pop button', (els) =>
    els.map((e) => e.getAttribute("aria-label")));
  console.log('   options:', options.join(', '));

  // 3. choose a 2-slot layout, then place two photos
  await page.click('.layout-pop button[aria-label="two-v"]');
  await page.waitForTimeout(400);
  await page.click('#tray-grid .ph-card:nth-child(1)');
  await page.waitForTimeout(300);
  await page.click('#tray-grid .ph-card:nth-child(2)');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'), undefined,
    { timeout: 20000 });
  const onCanvas = await page.$$eval('#page-canvas .placement', (els) => els.length);
  console.log('3. placements on canvas:', onCanvas);

  const creds = await page.evaluate(() => JSON.parse(localStorage.getItem('mb-book')));
  const book = await (await fetch(`http://127.0.0.1:8000/api/v1/books/${creds.book_id}`,
    { headers: { 'X-Edit-Token': creds.edit_token } })).json();
  const saved = book.layout.pages[0].placements;
  console.log('   placements saved on server:', saved.length,
    saved.map((p) => `${p.w_mm}x${p.h_mm}`).join(' '));
  if (saved.length < 2) throw new Error('second photo did not persist');

  // 4. centre snapping while dragging
  await page.click('#filmstrip .film-item:nth-child(3)');   // fresh page 2
  await page.click('#tray-grid .ph-card:nth-child(3)');
  await page.click('#filmstrip .film-item:nth-child(3)');   // filling auto-advances
  await page.waitForSelector('#page-canvas .placement');
  await page.click('#btn-layout');
  await page.click('.layout-pop button[aria-label="inset"]');
  await page.waitForTimeout(300);
  const pbox = await (await page.$('#page-canvas .placement')).boundingBox();
  const canvas = await (await page.$('#page-canvas')).boundingBox();
  // drag it a few px off-centre horizontally; snapping should pull it back
  const targetX = canvas.x + canvas.width / 2 + 4;
  const targetY = canvas.y + canvas.height / 2 + 4;
  await page.mouse.move(pbox.x + pbox.width / 2, pbox.y + pbox.height / 2);
  await page.mouse.down();
  await page.mouse.move(targetX - 40, targetY - 40, { steps: 6 });
  await page.mouse.move(targetX, targetY, { steps: 6 });
  const guideDuringDrag = await page.$$eval('.snap-guide', (els) => els.length);
  await page.mouse.up();
  await page.waitForTimeout(300);
  const after = await page.evaluate(() => {
    const c = JSON.parse(localStorage.getItem('mb-book'));
    void c;
    const el = document.querySelector('#page-canvas .placement');
    const cv = document.getElementById('page-canvas').getBoundingClientRect();
    const r = el.getBoundingClientRect();
    return { dx: (r.left + r.width / 2) - (cv.left + cv.width / 2),
             dy: (r.top + r.height / 2) - (cv.top + cv.height / 2) };
  });
  console.log('4. snap guides visible during drag:', guideDuringDrag);
  console.log('   offset from page centre after drop: dx=%s dy=%s px',
    after.dx.toFixed(1), after.dy.toFixed(1));
  if (Math.abs(after.dx) > 2 || Math.abs(after.dy) > 2) {
    throw new Error('did not snap to centre');
  }

  console.log('errors:', errors.length ? errors : 'none');
  await page.screenshot({ path: SHOTS + '/83-layout-check.png' });
  await browser.close();
  if (errors.length) throw new Error('page errors');
  console.log('LAYOUT+SNAP CHECK PASSED (shipped code works locally)');
})().catch((e) => { console.error('FAILED', e.message); process.exit(1); });
