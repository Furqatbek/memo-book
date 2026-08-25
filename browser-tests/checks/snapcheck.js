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
  await page.click('.btype[data-btype="memory"]');
  await page.click('.tier[data-tier="16"]');
  // A71 put a cover-design gallery between size and editor.
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');
  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('1 '), undefined, { timeout: 60000 });
  await page.click('#filmstrip .film-item:nth-child(2)');       // page 1
  await page.click('#tray-grid .ph-card:nth-child(1)');          // place it
  // filling the page auto-advances the view — come back to the filled page
  await page.click('#filmstrip .film-item:nth-child(2)');
  await page.waitForSelector('#page-canvas .placement', { timeout: 15000 });
  await page.click('#btn-layout');
  await page.click('.layout-pop button[aria-label="inset"]');    // smaller than page
  await page.waitForTimeout(400);

  const cv = await (await page.$('#page-canvas')).boundingBox();
  const pb = await (await page.$('#page-canvas .placement')).boundingBox();
  const cx = cv.x + cv.width / 2, cy = cv.y + cv.height / 2;
  // start from the element centre, drag to 6px past page centre on both axes
  await page.mouse.move(pb.x + pb.width / 2, pb.y + pb.height / 2);
  await page.mouse.down();
  await page.mouse.move(cx - 30, cy - 30, { steps: 6 });
  await page.mouse.move(cx + 6, cy + 6, { steps: 6 });
  const guides = await page.$$eval('.snap-guide', (e) => e.length);
  await page.screenshot({ path: SHOTS + '/84-snap-during-drag.png' });
  await page.mouse.up();
  await page.waitForTimeout(300);
  const off = await page.evaluate(() => {
    const el = document.querySelector('#page-canvas .placement');
    const c = document.getElementById('page-canvas').getBoundingClientRect();
    const r = el.getBoundingClientRect();
    return { dx: (r.left + r.width / 2) - (c.left + c.width / 2),
             dy: (r.top + r.height / 2) - (c.top + c.height / 2) };
  });
  console.log('snap guides shown while latched:', guides);
  console.log('offset from centre after drop: dx=%s dy=%s px', off.dx.toFixed(1), off.dy.toFixed(1));
  const snapped = Math.abs(off.dx) < 2 && Math.abs(off.dy) < 2;
  console.log('snapped to centre:', snapped);
  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  if (!snapped) { console.log('SNAP NOT WORKING'); process.exit(2); }
  console.log('SNAP CHECK PASSED');
})().catch((e) => { console.error('FAILED', e.message); process.exit(1); });
