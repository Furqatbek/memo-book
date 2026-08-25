/* Free-form editing E2E: type anywhere (dblclick), drag text, resize photo,
   page/cover/title colours — all persisted to the backend layout. */
const { chromium } = require('playwright');
const path = require('path');

const BASE = 'http://127.0.0.1:8000';
const PHOTOS = Array.from({ length: 3 }, (_, i) =>
  path.join(__dirname, '..', 'fixtures', `photo${String(i).padStart(2, '0')}.jpg`));
const SHOT = (n) => path.join(__dirname, 'shots', n);

async function waitSaved(page) {
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'), undefined,
    { timeout: 30000 });
}

async function setColor(page, container, index, value) {
  await page.locator(`${container} .color-tool`).nth(index).click();
  await page.waitForSelector('.swatch-pop input[type=color]');
  await page.$eval('.swatch-pop input[type=color]', (el, v) => {
    el.value = v;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }, value);
  await page.keyboard.press('Escape').catch(() => {});
  await page.mouse.click(5, 5);
}

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 1360, height: 850 } });
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));

  await page.goto(`${BASE}/editor/`);
  await page.click('.btype[data-btype=\"memory\"]');
  await page.click('.tier[data-tier="16"]');
  // A71 put a cover-design gallery between size and editor.
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');
  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('3 '), undefined,
    { timeout: 60000 });

  // --- page 1: place a photo ---
  await page.click('#filmstrip .film-item:nth-child(2)');
  await page.click('#tray-grid .ph-card:first-child');
  await waitSaved(page);
  await page.click('#filmstrip .film-item:nth-child(2)');   // auto-advance moved on

  // --- type anywhere: dblclick upper-left area of the canvas ---
  const c = await (await page.$('#page-canvas')).boundingBox();
  await page.mouse.dblclick(c.x + c.width * 0.35, c.y + c.height * 0.25);
  await page.keyboard.type('Hello Samarkand');
  await waitSaved(page);
  const contentAfterType = await page.textContent('.textbox-content');
  if (!contentAfterType.includes('Hello Samarkand')) throw new Error('type-anywhere failed');

  // --- drag the text box by its body to a new spot ---
  await page.mouse.click(c.x + c.width * 0.9, c.y + c.height * 0.93); // blur/deselect
  const tb = await (await page.$('.textbox')).boundingBox();
  const leftBefore = await page.$eval('.textbox', (el) => el.style.left);
  await page.mouse.move(tb.x + tb.width / 2, tb.y + tb.height / 2);
  await page.mouse.down();
  await page.mouse.move(tb.x + tb.width / 2 + 120, tb.y + tb.height / 2 + 150, { steps: 12 });
  await page.mouse.up();
  await waitSaved(page);
  const leftAfter = await page.$eval('.textbox', (el) => el.style.left);
  if (leftBefore === leftAfter) throw new Error('text drag did not move the box');

  // --- text colour via the selection toolbar ---
  await setColor(page, '#sel-toolbar', 0, '#cc2200');
  await waitSaved(page);

  // --- select the photo, resize via the SE corner handle ---
  const pl = await (await page.$('.placement')).boundingBox();
  await page.mouse.click(pl.x + 30, pl.y + pl.height - 30);
  await page.waitForSelector('.placement .rs.se');
  const se = await (await page.$('.placement .rs.se')).boundingBox();
  await page.mouse.move(se.x + 7, se.y + 7);
  await page.mouse.down();
  await page.mouse.move(se.x + 7 - 140, se.y + 7 - 160, { steps: 12 });
  await page.mouse.up();
  await waitSaved(page);

  // --- drag the (now smaller) photo toward the centre ---
  // Off-centre: the middle of a selected photo is the crop-pan grip, which
  // moves the photo inside its frame rather than the frame itself.
  const pl2 = await (await page.$('.placement')).boundingBox();
  const gx = pl2.x + pl2.width * 0.25, gy = pl2.y + pl2.height * 0.25;
  await page.mouse.move(gx, gy);
  await page.mouse.down();
  await page.mouse.move(gx + 60, gy + 40, { steps: 10 });
  await page.mouse.up();
  await waitSaved(page);

  // --- page background colour ---
  await setColor(page, '#page-tools', 0, '#ffe8cc');
  await waitSaved(page);
  await page.screenshot({ path: SHOT('20-freeform-page.png') });

  // --- cover: photo + colours + title ---
  await page.click('#filmstrip .film-item:first-child');
  await page.click('#tray-grid .ph-card:nth-child(2)');
  await page.fill('.cover-title', 'Bizning Sayohat');
  await waitSaved(page);
  const coverTools = await page.$$('#page-tools .color-tool');
  if (coverTools.length !== 2) throw new Error('expected cover bg + title colour tools');
  await setColor(page, '#page-tools', 0, '#123a5e');
  await setColor(page, '#page-tools', 1, '#ffd700');
  await waitSaved(page);
  await page.screenshot({ path: SHOT('21-freeform-cover.png') });

  // --- verify everything persisted server-side ---
  const creds = await page.evaluate(() => JSON.parse(localStorage.getItem('mb-book')));
  const resp = await fetch(`${BASE}/api/v1/books/${creds.book_id}`,
                           { headers: { 'X-Edit-Token': creds.edit_token } });
  const book = await resp.json();
  const p0 = book.layout.pages[0];
  const text = p0.texts[0];
  const plc = p0.placements[0];
  const cov = book.layout.cover;
  const checks = {
    'text content': text.content === 'Hello Samarkand',
    'text moved': Math.abs(text.x_mm - 39) > 3 || Math.abs(text.y_mm - 45.5) > 3,
    'text colour': text.color === '#cc2200',
    'photo resized': plc.w_mm < 150 && plc.h_mm < 212,
    'photo moved': plc.x_mm > -3 || plc.y_mm > -3,
    'page bg': p0.bg_color === '#ffe8cc',
    'cover bg': cov.bg_color === '#123a5e',
    'cover title colour': cov.title_color === '#ffd700',
    'cover title': cov.title === 'Bizning Sayohat',
  };
  console.log(JSON.stringify({ text, plc: { x: plc.x_mm, y: plc.y_mm, w: plc.w_mm, h: plc.h_mm } }));
  const failed = Object.entries(checks).filter(([, ok]) => !ok);
  if (failed.length) throw new Error('persistence checks failed: ' + failed.map(([k]) => k).join(', '));

  console.log('console errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) process.exit(2);
  console.log('FREEFORM E2E PASSED');
})().catch((e) => { console.error('FREEFORM E2E FAILED:', e); process.exit(1); });
