/* A71: changing a ready-made cover after the book exists.
 *
 * Picking the wrong design at the start must not be permanent, and taking a
 * design off must leave the customer's own words and photo alone.
 *
 * Seeds its own catalogue through the admin API, so it needs ADMIN_TOKEN
 * (the dev server sets `dev-admin` by default).
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const BASE = 'http://127.0.0.1:8000';
const TOKEN = 'dev-admin';
const ART = path.join(__dirname, '..', 'fixtures', 'artwork-hearts.png');
const PHOTO = path.join(__dirname, '..', 'fixtures', 'photo01.jpg');

const SEED = [
  { slug: 'swap-a', name: 'Swap A', bg: '#1d4d85',
    rect: '{"x_mm":19,"y_mm":24,"w_mm":110,"h_mm":110}' },
  { slug: 'swap-b', name: 'Swap B', bg: '#efe9dd',
    rect: '{"x_mm":26,"y_mm":26,"w_mm":96,"h_mm":130}' },
];

async function seedDesigns() {
  const bytes = fs.readFileSync(ART);
  const ids = {};
  for (const d of SEED) {
    const form = new FormData();
    form.append('slug', d.slug);
    form.append('name', d.name);
    form.append('book_types', 'travel');
    form.append('bg_color', d.bg);
    form.append('photo_rect', d.rect);
    form.append('title', '{"x_mm":74,"y_mm":170,"size_pt":24}');
    form.append('artwork', new Blob([bytes], { type: 'image/png' }), 'a.png');
    const resp = await fetch(`${BASE}/api/v1/admin/cover-designs`, {
      method: 'POST', headers: { 'X-Admin-Token': TOKEN }, body: form,
    });
    if (!resp.ok) {
      throw new Error(`could not seed ${d.slug}: ${resp.status} `
        + `— is ADMIN_TOKEN set to "${TOKEN}"?`);
    }
    ids[d.slug] = (await resp.json()).design_id;
  }
  return ids;
}

(async () => {
  const ids = await seedDesigns();

  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1240, height: 950 } })).newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  // start a travel book on design A
  await page.goto(`${BASE}/editor/`);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/editor/`);
  await page.click('.btype[data-btype="travel"]');
  await page.waitForFunction(() => document.querySelector('[data-tier-pages]').textContent,
    undefined, { timeout: 10000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#design-step:not(.hidden)', { timeout: 20000 });
  await page.click('#design-grid .design-card[data-design="swap-a"]');
  await page.waitForSelector('#screen-editor.active');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 20000 });

  const creds = await page.evaluate(() => JSON.parse(localStorage.getItem('mb-book')));
  const load = async () => (await fetch(`${BASE}/api/v1/books/${creds.book_id}`,
    { headers: { 'X-Edit-Token': creds.edit_token } })).json();
  const saved = () => page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 20000 });

  // give the customer something of their own to lose
  await page.setInputFiles('#file-input', [PHOTO]);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('1 '),
    undefined, { timeout: 120000 });
  await page.click('#filmstrip .film-item:first-child');
  await page.click('#tray-grid .ph-card:nth-child(1)');
  await page.waitForSelector('#page-canvas .cover-frame img');
  await page.fill('.cover-title', 'Samarkand 2026');
  await saved();

  // 1. the changer is offered on the cover, and only there
  console.log('1. changer on the cover:', await page.isVisible('#btn-cover-design'));
  await page.click('#filmstrip .film-item:nth-child(2)');
  console.log('   hidden on an inside page:', !await page.isVisible('#btn-cover-design'));
  if (await page.isVisible('#btn-cover-design')) {
    throw new Error('the cover-design changer showed on a page');
  }
  await page.click('#filmstrip .film-item:first-child');

  // 2. it offers every design plus "no design"
  await page.click('#btn-cover-design');
  await page.waitForSelector('.design-pop');
  const options = await page.$$eval('.design-pop .lay-item',
    (els) => els.map((e) => e.getAttribute('aria-label')));
  console.log('2. options:', options.length, 'including "none":',
    options.includes('none'));
  if (!options.includes('none')) throw new Error('no way to remove the design');
  if (!options.includes(ids['swap-b'])) throw new Error('the other design is missing');

  // 3. swap A -> B: the design and its colour change together
  const before = (await load()).layout.cover;
  await page.click(`.design-pop .lay-item[aria-label="${ids['swap-b']}"]`);
  await saved();
  const after = (await load()).layout.cover;
  console.log('3. swapped:', JSON.stringify({
    from: before.bg_color, to: after.bg_color, rect: after.photo_rect }));
  if (after.design_id !== ids['swap-b']) throw new Error('the swap did not stick');
  if (after.bg_color !== '#efe9dd') throw new Error('the new design kept the old colour');
  if (after.photo_rect.w_mm !== 96) throw new Error('the photo window did not move');

  // 4. the customer's own content survived the swap
  console.log('4. after the swap -> title:', JSON.stringify(after.title),
    '| photo kept:', !!after.photo_id);
  if (after.title !== 'Samarkand 2026' || !after.photo_id) {
    throw new Error('swapping the design ate the customer content');
  }

  // 5. "no design" removes the artwork and nothing else
  await page.click('#btn-cover-design');
  await page.waitForSelector('.design-pop');
  await page.click('.design-pop .lay-item[aria-label="none"]');
  await saved();
  const plain = (await load()).layout.cover;
  console.log('5. no design -> design_id:', plain.design_id,
    '| title:', JSON.stringify(plain.title), '| photo kept:', !!plain.photo_id);
  if (plain.design_id) throw new Error('removing the design did not stick');
  if (plain.title !== 'Samarkand 2026' || !plain.photo_id) {
    throw new Error('removing the design ate the customer content');
  }
  if (await page.$('#page-canvas .cover-art')) {
    throw new Error('artwork still drawn after removal');
  }
  console.log('   artwork gone from the canvas: true');

  // 6. and it can be put back
  await page.click('#btn-cover-design');
  await page.waitForSelector('.design-pop');
  await page.click(`.design-pop .lay-item[aria-label="${ids['swap-a']}"]`);
  await saved();
  await page.waitForSelector('#page-canvas .cover-art', { timeout: 20000 });
  const back = (await load()).layout.cover;
  console.log('6. put back ->', back.design_id === ids['swap-a'],
    '| colour:', back.bg_color);
  if (back.design_id !== ids['swap-a']) throw new Error('could not go back');

  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) throw new Error('page errors');
  console.log('DESIGN SWAP CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
