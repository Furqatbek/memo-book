const { chromium } = require('playwright');
const path = require('path');
const SHOTS = path.join(__dirname, '..', 'shots');
const PHOTOS = [path.join(__dirname, '..', 'fixtures', 'photo00.jpg')];
const bbox = async (page, sel) => (await page.$(sel)).boundingBox();
const saved = (page) => page.waitForFunction(
  () => document.getElementById('save-state').classList.contains('saved'), undefined, { timeout: 30000 });
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, hasTouch: true });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto('http://127.0.0.1:8000/editor/');
  await page.click('.btype[data-btype=\"memory\"]');
  await page.click('.tier[data-tier="16"]');
  // A71 put a cover-design gallery between size and editor.
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');

  // type the title
  await page.click('.cover-title');
  await page.keyboard.type('Sayohat');
  await saved(page);
  // blur: tap an empty canvas corner
  const cv = await bbox(page, '#page-canvas');
  await page.mouse.click(cv.x + 12, cv.y + 12);

  // drag the block up-left (fresh bbox)
  let b = await bbox(page, '.cover-titles');
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width / 2 - 50, b.y + b.height / 2 - 120, { steps: 10 });
  await page.mouse.up();
  await saved(page);

  // select -> handles appear (fresh bbox)
  b = await bbox(page, '.cover-titles');
  await page.mouse.click(b.x + b.width / 2, b.y + 6);
  await page.waitForSelector('.cover-titles.sel .tb-rotate', { timeout: 10000 });

  // rotate via the handle
  const rot = await bbox(page, '.cover-titles .tb-rotate');
  b = await bbox(page, '.cover-titles');
  const bcx = b.x + b.width / 2, bcy = b.y + b.height / 2;
  await page.mouse.move(rot.x + rot.width / 2, rot.y + rot.height / 2);
  await page.mouse.down();
  await page.mouse.move(bcx + 90, bcy - 30, { steps: 10 });
  await page.mouse.up();
  await saved(page);

  // scale via the corner dot
  const sc = await bbox(page, '.cover-titles .tb-scale');
  await page.mouse.move(sc.x + sc.width / 2, sc.y + sc.height / 2);
  await page.mouse.down();
  await page.mouse.move(sc.x + 80, sc.y + 60, { steps: 10 });
  await page.mouse.up();
  await saved(page);
  await page.screenshot({ path: SHOTS + '/90-cover-free.png' });

  // ---- PINCH a placed photo (synthetic touch pointers) ----
  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('1 '), undefined, { timeout: 60000 });
  await page.click('#filmstrip .film-item:nth-child(2)');
  await page.click('#tray-grid .ph-card:first-child');
  await page.click('#filmstrip .film-item:nth-child(2)');
  await saved(page);
  const widthAfter = await page.evaluate(async () => {
    const el = document.querySelector('.placement');
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const ev = (type, id, x, y) => new PointerEvent(type, {
      pointerId: id, pointerType: 'touch', isPrimary: id === 1,
      clientX: x, clientY: y, bubbles: true, cancelable: true,
    });
    el.dispatchEvent(ev('pointerdown', 1, cx - 30, cy));
    el.dispatchEvent(ev('pointerdown', 2, cx + 30, cy));
    for (let i = 1; i <= 8; i++) {
      const dx = 30 - i * 2.2;
      window.dispatchEvent(ev('pointermove', 1, cx - dx, cy));
      window.dispatchEvent(ev('pointermove', 2, cx + dx, cy));
      await new Promise((res) => setTimeout(res, 10));
    }
    window.dispatchEvent(ev('pointerup', 1, cx - 12, cy));
    window.dispatchEvent(ev('pointerup', 2, cx + 12, cy));
    return document.querySelector('.placement').style.width;
  });
  console.log('placement width after pinch-in:', widthAfter);
  await saved(page);

  const creds = await page.evaluate(() => JSON.parse(localStorage.getItem('mb-book')));
  const book = await (await fetch(`http://127.0.0.1:8000/api/v1/books/${creds.book_id}`,
    { headers: { 'X-Edit-Token': creds.edit_token } })).json();
  const cov = book.layout.cover;
  const plc = book.layout.pages[0].placements[0];
  console.log('cover:', JSON.stringify({ x: cov.title_x_mm, y: cov.title_y_mm,
    rot: cov.title_rotation, size: cov.title_size_pt, title: cov.title }));
  console.log('placement w_mm after pinch:', plc.w_mm.toFixed(1));
  const checks = {
    'cover moved': cov.title_x_mm !== null && cov.title_x_mm < 70,
    'cover rotated': !!cov.title_rotation,
    'cover scaled': cov.title_size_pt !== 28,
    'photo pinched smaller': plc.w_mm < 150,
  };
  const failed = Object.entries(checks).filter(([, ok]) => !ok);
  if (failed.length) throw new Error('failed: ' + failed.map(([k]) => k).join(', '));
  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  console.log('COVER + PINCH CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
