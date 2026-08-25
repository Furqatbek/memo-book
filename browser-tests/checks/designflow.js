/* A71: ready-made cover designs — occasion, size, then a cover chosen from a
 * gallery the SERVER filtered. The design has to reach the book, the editor
 * canvas and the print file, and survive a reload.
 *
 * Seeds its own catalogue through the admin API so it depends on no manual
 * setup — which also means it needs ADMIN_TOKEN (the dev server sets
 * `dev-admin` by default).
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const SHOTS = path.join(__dirname, '..', 'shots');
const BASE = 'http://127.0.0.1:8000';
const TOKEN = 'dev-admin';
const ART = path.join(__dirname, '..', 'fixtures', 'artwork-hearts.png');
const PHOTO = path.join(__dirname, '..', 'fixtures', 'photo00.jpg');

/* One artwork file, three designs: two aimed at an occasion each and one
   left open, which is what makes the filtering visible. */
const SEED = [
  { slug: 'flow-love', name: 'Flow hearts', types: 'love', order: '11',
    rect: '{"x_mm":24,"y_mm":150,"w_mm":100,"h_mm":42}' },
  { slug: 'flow-travel', name: 'Flow compass', types: 'travel', order: '12',
    rect: '{"x_mm":19,"y_mm":24,"w_mm":110,"h_mm":110}' },
  { slug: 'flow-any', name: 'Flow linen', types: '', order: '13', rect: '' },
];

async function seedDesigns() {
  const bytes = fs.readFileSync(ART);
  for (const d of SEED) {
    const form = new FormData();
    form.append('slug', d.slug);
    form.append('name', d.name);
    form.append('book_types', d.types);
    form.append('sort_order', d.order);
    form.append('bg_color', '#1d4d85');
    form.append('title_color', '#ffffff');
    form.append('title', '{"x_mm":74,"y_mm":158,"size_pt":26}');
    if (d.rect) form.append('photo_rect', d.rect);
    form.append('artwork', new Blob([bytes], { type: 'image/png' }), 'a.png');
    const resp = await fetch(`${BASE}/api/v1/admin/cover-designs`, {
      method: 'POST', headers: { 'X-Admin-Token': TOKEN }, body: form,
    });
    if (!resp.ok) {
      throw new Error(`could not seed ${d.slug}: ${resp.status} `
        + `— is ADMIN_TOKEN set to "${TOKEN}"?`);
    }
  }
}

/* Occasion -> size -> the gallery. Returns the design slugs it offers. */
async function galleryFor(page, type) {
  await page.goto(`${BASE}/editor/`);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/editor/`);
  await page.click(`.btype[data-btype="${type}"]`);
  await page.waitForFunction(() => document.querySelector('[data-tier-pages]').textContent,
    undefined, { timeout: 10000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#design-step:not(.hidden)', { timeout: 20000 });
  return page.$$eval('#design-grid .design-card', (els) => els.map((e) => e.dataset.design));
}

(async () => {
  await seedDesigns();

  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1200, height: 950 } })).newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  // 1. the backend filters the shelf by occasion
  const seen = {};
  for (const type of ['love', 'travel', 'birthday', 'memory']) {
    seen[type] = (await galleryFor(page, type)).filter((s) => s.startsWith('flow-'));
    console.log(`1. ${type.padEnd(9)}`, seen[type].join(', '));
  }
  if (!seen.love.includes('flow-love') || seen.love.includes('flow-travel')) {
    throw new Error('a love customer saw the wrong shelf');
  }
  if (!seen.travel.includes('flow-travel') || seen.travel.includes('flow-love')) {
    throw new Error('a travel customer saw the wrong shelf');
  }
  for (const type of Object.keys(seen)) {
    if (!seen[type].includes('flow-any')) {
      throw new Error(`the open design is missing from ${type}`);
    }
  }

  // 2. the step names the size and can go back to change it
  await galleryFor(page, 'travel');
  console.log('2. step label:', JSON.stringify((await page.textContent('#design-chosen')).trim()));
  await page.click('#design-back');
  console.log('   back returns to the size step:',
    await page.isVisible('#tier-step') && !await page.isVisible('#design-step'));
  await page.screenshot({ path: SHOTS + '/90-design-gallery.png' });

  // 3. choosing one opens the book with it
  await page.click('.tier[data-tier="32"]');
  await page.waitForSelector('#design-step:not(.hidden)');
  await page.click('#design-grid .design-card[data-design="flow-travel"]');
  await page.waitForSelector('#screen-editor.active');
  await page.waitForSelector('#page-canvas .cover-art', { timeout: 20000 });
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 20000 });

  const creds = await page.evaluate(() => JSON.parse(localStorage.getItem('mb-book')));
  const load = async () => (await fetch(`${BASE}/api/v1/books/${creds.book_id}`,
    { headers: { 'X-Edit-Token': creds.edit_token } })).json();
  const book = await load();
  const c = book.layout.cover;
  console.log('3. stored on the book:', JSON.stringify({
    design: !!c.design_id, rect: c.photo_rect, bg: c.bg_color,
    title: [c.title_x_mm, c.title_y_mm, c.title_size_pt] }));
  if (!c.design_id) throw new Error('the design never reached the book');
  if (c.bg_color !== '#1d4d85') throw new Error('the design did not bring its colour');
  console.log('   book:', book.page_count, 'pages |', book.book_type);

  // 4. the customer's photo lands in the design's window, under nothing
  await page.setInputFiles('#file-input', [PHOTO]);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('1 '),
    undefined, { timeout: 120000 });
  await page.click('#tray-grid .ph-card:nth-child(1)');
  await page.waitForSelector('#page-canvas .cover-frame img');
  const frame = await page.evaluate(() => {
    const cv = document.getElementById('page-canvas').getBoundingClientRect();
    const f = document.querySelector('#page-canvas .cover-frame').getBoundingClientRect();
    const r = (n) => Math.round(n * 1000) / 10;
    return { left: r((f.x - cv.x) / cv.width), top: r((f.y - cv.y) / cv.height),
             w: r(f.width / cv.width), h: r(f.height / cv.height) };
  });
  console.log('4. photo frame (% of canvas):', JSON.stringify(frame));
  const behind = await page.evaluate(() => {
    const art = getComputedStyle(document.querySelector('#page-canvas .cover-art'));
    const fr = getComputedStyle(document.querySelector('#page-canvas .cover-frame'));
    return Number(art.zIndex || 0) < Number(fr.zIndex || 0);
  });
  console.log('   artwork sits behind the photo:', behind);
  if (!behind) throw new Error('artwork drawn over the photo');
  await page.locator('#page-canvas').screenshot({ path: SHOTS + '/90-design-cover.png' });

  // 5. a resumed book gets its artwork back
  await page.reload();
  await page.waitForSelector('#resume-card:not(.hidden)', { timeout: 20000 });
  await page.click('#btn-resume');
  await page.waitForSelector('#screen-editor.active', { timeout: 20000 });
  await page.click('#filmstrip .film-item:first-child');
  await page.waitForSelector('#page-canvas .cover-art', { timeout: 20000 });
  console.log('5. artwork restored after a reload: true');

  // 6. "use my own photo" leaves the cover plain
  await page.evaluate(() => localStorage.clear());
  await galleryFor(page, 'love');
  await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 20000 });
  const plainCreds = await page.evaluate(() => JSON.parse(localStorage.getItem('mb-book')));
  const plain = await (await fetch(`${BASE}/api/v1/books/${plainCreds.book_id}`,
    { headers: { 'X-Edit-Token': plainCreds.edit_token } })).json();
  console.log('6. skip -> design_id:', plain.layout.cover.design_id,
    '| occasion colour kept:', plain.layout.cover.bg_color);
  if (plain.layout.cover.design_id) throw new Error('skip still set a design');
  if (await page.$('#page-canvas .cover-art')) throw new Error('artwork on a skipped cover');
  console.log('   no artwork on the canvas: true');

  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) throw new Error('page errors');
  console.log('DESIGN FLOW CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
