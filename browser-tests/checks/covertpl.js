/* A70: the five built-in cover compositions — full photo, framed, photo on
 * top, title on top, square.
 *
 * Upload one photo, tap it, and the cover is finished. The Layout button
 * offers the compositions on the cover and photo grids on a page, and what
 * the editor draws must be the geometry the server stores.
 */
const { chromium } = require('playwright');
const path = require('path');
const SHOTS = path.join(__dirname, '..', 'shots');
const BASE = 'http://127.0.0.1:8000';
const PHOTOS = [path.join(__dirname, '..', 'fixtures', 'photo00.jpg'),
                path.join(__dirname, '..', 'fixtures', 'photo01.jpg')];

/* The composition each template applies, in front-panel trim mm. Written out
   rather than read from the app, so this disagrees loudly if the registry
   moves without anyone meaning it to. */
const EXPECTED = {
  full:     { x_mm: 0,  y_mm: 0,  w_mm: 148, h_mm: 210 },
  window:   { x_mm: 16, y_mm: 16, w_mm: 116, h_mm: 145 },
  band:     { x_mm: 0,  y_mm: 0,  w_mm: 148, h_mm: 138 },
  banner:   { x_mm: 0,  y_mm: 72, w_mm: 148, h_mm: 138 },
  polaroid: { x_mm: 19, y_mm: 24, w_mm: 110, h_mm: 110 },
};

const same = (a, b) => a && b
  && ['x_mm', 'y_mm', 'w_mm', 'h_mm'].every((k) => Math.abs(a[k] - b[k]) < 0.01);

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1360, height: 950 } })).newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto(`${BASE}/editor/`);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/editor/`);
  await page.click('.btype[data-btype="travel"]');
  await page.waitForFunction(() => document.querySelector('[data-tier-pages]').textContent,
    undefined, { timeout: 10000 });
  await page.click('.tier[data-tier="16"]');
  // A71 put a cover-design gallery between size and editor; the built-in
  // compositions are what you get when you bring your own photo.
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');

  // 1. the Layout button is offered on the cover
  await page.click('#filmstrip .film-item:first-child');
  console.log('1. Layout button on the cover:', await page.isVisible('#btn-layout'),
    '| label:', JSON.stringify((await page.textContent('#btn-layout')).trim()));

  // 2. one photo, one tap — that is the whole job
  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('2 '),
    undefined, { timeout: 120000 });
  await page.click('#tray-grid .ph-card:nth-child(1)');
  await page.waitForSelector('#page-canvas .cover-frame img');
  console.log('2. one tap put the photo on the cover: true');

  const creds = await page.evaluate(() => JSON.parse(localStorage.getItem('mb-book')));
  const load = async () => (await fetch(`${BASE}/api/v1/books/${creds.book_id}`,
    { headers: { 'X-Edit-Token': creds.edit_token } })).json();

  const frame = () => page.evaluate(() => {
    const cv = document.getElementById('page-canvas').getBoundingClientRect();
    const f = document.querySelector('#page-canvas .cover-frame').getBoundingClientRect();
    const r = (n) => Math.round(n * 1000) / 10;
    return { left: r((f.x - cv.x) / cv.width), top: r((f.y - cv.y) / cv.height),
             w: r(f.width / cv.width), h: r(f.height / cv.height) };
  });
  console.log('   default frame (% of canvas):', JSON.stringify(await frame()));

  // 3. the picker offers all five, named
  await page.click('#btn-layout');
  await page.waitForSelector('.layout-pop');
  const offered = await page.$$eval('.layout-pop .lay-item', (els) => els.map(
    (e) => `${e.getAttribute('aria-label')}:${e.querySelector('.lay-name').textContent}`));
  console.log('3. designs offered:', offered.join(', '));
  if (offered.length !== 5) throw new Error(`expected 5 compositions, got ${offered.length}`);
  if (!offered[0].startsWith('full:')) {
    throw new Error('the default composition is not offered first');
  }

  // 4. each one moves the frame, and the server agrees with the editor
  for (const id of ['window', 'band', 'banner', 'polaroid', 'full']) {
    if (!await page.$('.layout-pop')) await page.click('#btn-layout');
    await page.waitForSelector('.layout-pop');
    await page.click(`.layout-pop .lay-item[aria-label="${id}"]`);
    await page.waitForFunction(
      () => document.getElementById('save-state').classList.contains('saved'),
      undefined, { timeout: 20000 });
    const c = (await load()).layout.cover;
    console.log(`4. ${id.padEnd(9)} rect:`, JSON.stringify(c.photo_rect),
      '| title', `${c.title_x_mm},${c.title_y_mm}`, `${c.title_size_pt}pt`,
      '| on screen:', JSON.stringify(await frame()));
    if (c.template !== id) throw new Error(`${id}: server kept template ${c.template}`);
    if (!same(c.photo_rect, EXPECTED[id])) {
      throw new Error(`${id}: rect ${JSON.stringify(c.photo_rect)} `
        + `is not ${JSON.stringify(EXPECTED[id])}`);
    }
  }
  await page.locator('#page-canvas').screenshot({ path: SHOTS + '/90-cover-full.png' });

  // 5. the words, the photo and the colour survived all five
  const after = (await load()).layout.cover;
  console.log('5. survived:', JSON.stringify({
    title: after.title, photo: !!after.photo_id, bg: after.bg_color }));
  if (!after.title || !after.photo_id) throw new Error('a composition ate the content');
  if (after.bg_color !== '#1d4d85') {
    throw new Error('a composition changed the occasion colour');
  }

  // 6. an inside page still gets photo grids, not cover compositions
  await page.click('#filmstrip .film-item:nth-child(2)');
  await page.click('#btn-layout');
  await page.waitForSelector('.layout-pop');
  const pageOpts = await page.$$eval('.layout-pop .lay-item',
    (els) => els.map((e) => e.getAttribute('aria-label')).sort());
  console.log('6. page layouts unchanged:', pageOpts.join(', '));
  if (pageOpts.includes('polaroid') || pageOpts.includes('banner')) {
    throw new Error('cover compositions leaked onto a page');
  }
  await page.mouse.click(5, 5);

  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) throw new Error('page errors');
  console.log('COVER TEMPLATE CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
