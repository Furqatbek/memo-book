/* A65 + A66: a photo across the fold, and the gutter guide on the bound edge.
 *
 * Pages print one at a time, so a photo spanning a spread is stored on BOTH
 * pages — the same rectangle shifted by exactly one trim width (148 mm). If
 * that number ever drifts, the two printed halves stop meeting at the fold,
 * which is invisible on screen and ruinous on paper. This check exists
 * mostly to hold that 148 in place.
 *
 * Both features ride on placeRect/applyCrop, which the cover work also uses.
 */
const { chromium } = require('playwright');
const path = require('path');
const SHOTS = path.join(__dirname, '..', 'shots');
const BASE = 'http://127.0.0.1:8000';
const PHOTOS = [path.join(__dirname, '..', 'fixtures', 'photo00.jpg'),
                path.join(__dirname, '..', 'fixtures', 'photo01.jpg')];

const TRIM_W = 148;

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1400, height: 950 } })).newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto(`${BASE}/editor/`);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/editor/`);
  await page.click('.btype[data-btype="memory"]');
  await page.waitForFunction(() => document.querySelector('[data-tier-pages]').textContent,
    undefined, { timeout: 10000 });
  await page.click('.tier[data-tier="16"]');
  // A71 put a cover-design gallery between size and editor.
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');

  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('2 '),
    undefined, { timeout: 120000 });

  const creds = await page.evaluate(() => JSON.parse(localStorage.getItem('mb-book')));
  const load = async () => (await fetch(`${BASE}/api/v1/books/${creds.book_id}`,
    { headers: { 'X-Edit-Token': creds.edit_token } })).json();
  const saved = () => page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 20000 });

  // 1. page 1 stands alone on the right — no facing page, so no fold
  await page.click('#filmstrip .film-item:nth-child(2)');
  const lonely = !!await page.$('#facing-canvas');
  console.log('1. page 1 has a facing page:', lonely);
  if (lonely) throw new Error('page 1 was paired with something');

  // 2. page 2 faces page 3
  await page.click('#filmstrip .film-item:nth-child(3)');
  await page.click('#tray-grid .ph-card:nth-child(1)');
  await page.click('#filmstrip .film-item:nth-child(3)');
  await page.waitForSelector('#page-canvas .placement');
  await page.waitForSelector('#facing-canvas');
  console.log('2. page 2 shows its facing page:', true,
    '| label:', JSON.stringify(await page.textContent('.facing-label')));

  // 3. the gutter guide runs down the bound edge, alternating sides
  const gutters = await page.evaluate(() => [...document.querySelectorAll('.guide.gutter')]
    .map((el) => ({ side: el.classList.contains('bound-right') ? 'right' : 'left',
                    w: Math.round(el.getBoundingClientRect().width) })));
  console.log('3. gutter guides on screen:', JSON.stringify(gutters));
  if (gutters.length !== 2) throw new Error('expected a guide on each page of the spread');
  if (gutters[0].side === gutters[1].side) {
    throw new Error('both pages claim the same bound edge');
  }
  const pe = await page.$eval('.guide.gutter', (el) => getComputedStyle(el).pointerEvents);
  console.log('   the guide never blocks a drag:', pe === 'none');
  if (pe !== 'none') throw new Error('the gutter guide is clickable');
  await page.screenshot({ path: SHOTS + '/90-fold-spread.png' });

  // 4. span the photo across the fold
  await page.click('#page-canvas .placement');
  await page.waitForSelector('#sel-toolbar');
  const span = page.locator('#sel-toolbar button', { hasText: 'Across the fold' });
  console.log('4. across-the-fold offered:', await span.count() === 1);
  if (await span.count() !== 1) throw new Error('no way to span the fold');
  await span.click();
  await saved();

  let book = await load();
  const left = book.layout.pages[1].placements[0];
  const right = book.layout.pages[2].placements[0];
  console.log('5. left  half:', JSON.stringify({ x: left.x_mm, w: left.w_mm }));
  console.log('   right half:', JSON.stringify({ x: right.x_mm, w: right.w_mm }));
  if (Math.abs((left.x_mm - right.x_mm) - TRIM_W) > 0.01) {
    throw new Error(`the halves are ${left.x_mm - right.x_mm}mm apart, not ${TRIM_W}`);
  }
  if (!left.spread_id || left.spread_id !== right.spread_id) {
    throw new Error('the halves do not share a spread id');
  }
  if (left.photo_id !== right.photo_id) {
    throw new Error('the halves show different photos');
  }
  console.log('   exactly one trim width apart, sharing a spread id: true');

  // 6. cropping one half moves the other — they are one object
  await page.locator('#sel-toolbar button[title]').nth(1).click();   // zoom in
  await saved();
  book = await load();
  const l2 = book.layout.pages[1].placements[0];
  const r2 = book.layout.pages[2].placements[0];
  console.log('6. zoom after +:', l2.zoom, '/ far half:', r2.zoom);
  if (l2.zoom <= 1 || l2.zoom !== r2.zoom) throw new Error('the halves fell out of step');
  if (Math.abs((l2.x_mm - r2.x_mm) - TRIM_W) > 0.01) {
    throw new Error('zooming broke the fold alignment');
  }

  // 7. and it can be undone, leaving nothing behind on the far page
  await page.locator('#sel-toolbar button', { hasText: 'One page only' }).click();
  await saved();
  book = await load();
  console.log('7. after undo -> page 2:', book.layout.pages[1].placements.length,
    '| page 3:', book.layout.pages[2].placements.length);
  if (book.layout.pages[2].placements.length !== 0) {
    throw new Error('undo left a half behind');
  }
  if (book.layout.pages[1].placements[0].spread_id) {
    throw new Error('the remaining placement still claims a spread');
  }

  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) throw new Error('page errors');
  console.log('FOLD + GUTTER CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
