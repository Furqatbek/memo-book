/* A72: the admin console. Sign in, upload artwork, place the photo window by
   dragging, save — and the design must reach a real customer's gallery. */
const { chromium } = require('playwright');
const path = require('path');
const BASE = 'http://127.0.0.1:8000';
const ART = path.join(__dirname, '..', 'fixtures', 'artwork-hearts.png');
const TOKEN = 'dev-admin';

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 950 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto(`${BASE}/admin/`);
  await page.waitForSelector('#screen-login.active');

  // 1. a wrong token is refused, and says something useful
  await page.fill('#login-token', 'not-the-token');
  await page.click('#login-form button[type=submit]');
  await page.waitForSelector('#login-error:not(.hidden)');
  console.log('1. wrong token ->', JSON.stringify(
    (await page.textContent('#login-error')).slice(0, 60) + '...'));
  console.log('   still on the sign-in screen:', await page.isVisible('#screen-login'));
  // The refusal IS a 404 by design, so the browser logs one. Everything from
  // here on should be silent.
  errors.length = 0;

  // 2. the real token gets in
  await page.fill('#login-token', TOKEN);
  await page.click('#login-form button[type=submit]');
  await page.waitForSelector('#screen-main.active', { timeout: 15000 });
  console.log('2. signed in. artwork spec shown:',
    JSON.stringify((await page.textContent('#art-spec')).slice(0, 46) + '...'));

  // 3. create a design: artwork + fields. Orders is the landing tab now, so
  //    the designs section has to be asked for.
  await page.click('.tab[data-tab="designs"]');
  await page.waitForSelector('#tab-designs:not(.hidden)');
  await page.click('#btn-new');
  await page.waitForSelector('#edit-form:not(.hidden)');
  await page.setInputFiles('#f-artwork', ART);
  await page.waitForFunction(() => {
    const img = document.getElementById('cover-art');
    return img && !img.classList.contains('hidden') && img.getAttribute('src');
  }, undefined, { timeout: 10000 });
  console.log('3. artwork previews before upload: true');

  await page.fill('#f-slug', 'console-hearts');
  await page.fill('#f-name', 'Console hearts');
  await page.check('#f-types input[data-type="love"]');
  await page.check('#f-has-photo');
  await page.waitForSelector('#cover-photo:not(.hidden)');

  // 4. drag the photo window — the whole reason this is a UI
  const before = await page.evaluate(() => ({
    x: +document.getElementById('f-rect-x').value,
    y: +document.getElementById('f-rect-y').value,
  }));
  const box = await page.locator('#cover-photo').boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 26, box.y + box.height / 2 + 34,
                        { steps: 8 });
  await page.mouse.up();
  const after = await page.evaluate(() => ({
    x: +document.getElementById('f-rect-x').value,
    y: +document.getElementById('f-rect-y').value,
  }));
  console.log('4. drag moved the photo window:', JSON.stringify({ before, after }));
  if (after.x === before.x && after.y === before.y) {
    throw new Error('dragging the photo window did nothing');
  }

  // resize by the corner handle
  const wBefore = await page.evaluate(() => +document.getElementById('f-rect-w').value);
  const handle = await page.locator('#cover-photo .rs.se').boundingBox();
  await page.mouse.move(handle.x + 7, handle.y + 7);
  await page.mouse.down();
  await page.mouse.move(handle.x + 7 + 30, handle.y + 7 + 20, { steps: 6 });
  await page.mouse.up();
  const wAfter = await page.evaluate(() => +document.getElementById('f-rect-w').value);
  console.log('   corner handle resized it:', wBefore, '->', wAfter);
  if (wAfter <= wBefore) throw new Error('resize handle did nothing');

  // drag the title too
  const tBefore = await page.evaluate(() => +document.getElementById('f-title-y').value);
  const title = await page.locator('#cover-title').boundingBox();
  await page.mouse.move(title.x + title.width / 2, title.y + title.height / 2);
  await page.mouse.down();
  await page.mouse.move(title.x + title.width / 2, title.y + title.height / 2 - 40,
                        { steps: 6 });
  await page.mouse.up();
  const tAfter = await page.evaluate(() => +document.getElementById('f-title-y').value);
  console.log('   title dragged:', tBefore, '->', tAfter);

  // 5. save, and the customer gallery must show it
  await page.click('#btn-save');
  // Wait for the SAVE, not just for a row with this slug — a previous run may
  // have left one, and matching it would race the request.
  await page.waitForSelector(
    '.design-row[data-slug="console-hearts"]:not(.retired)', { timeout: 20000 });
  await page.waitForFunction(
    () => [...document.querySelectorAll('.design-row b')]
      .some((b) => b.textContent === 'Console hearts'),
    undefined, { timeout: 20000 });
  console.log('5. saved and listed in the console: true');

  const shop = await page.evaluate(async (base) => {
    const r = await fetch(`${base}/api/v1/cover-designs?book_type=love`);
    return (await r.json()).designs.map((d) => d.slug);
  }, BASE);
  console.log('   a love-story customer now sees:', shop.join(', '));
  if (!shop.includes('console-hearts')) throw new Error('never reached customers');

  const travel = await page.evaluate(async (base) => {
    const r = await fetch(`${base}/api/v1/cover-designs?book_type=travel`);
    return (await r.json()).designs.map((d) => d.slug);
  }, BASE);
  console.log('   a travel customer does not:', !travel.includes('console-hearts'));

  // 5b. A90: artwork that carries its own lettering must be able to say so.
  //     The backend has always accepted a design with no title; until now the
  //     console could not express it, so every design it produced got a title
  //     block whether the art wanted one or not.
  /* The console disables Save from the click until AFTER it has refreshed the
     list and repopulated the form from what came back. Waiting on the SERVER
     instead returns inside that window, and the next thing typed into a field
     is wiped by the repopulate — which is how step 6 came to be renaming a
     design that had already reset its own name box. Same lesson as A85: wait
     for the console to be ready, not for the data to have landed. */
  const settled = () => page.waitForFunction(
    () => !document.getElementById('btn-save').disabled,
    undefined, { timeout: 30000 });

  const titleOf = (slug) => page.evaluate(async ([base, s]) => {
    const r = await fetch(`${base}/api/v1/cover-designs?book_type=love`);
    const d = (await r.json()).designs.find((x) => x.slug === s);
    return d ? ('title' in d ? d.title : null) : 'MISSING';
  }, [BASE, 'console-hearts']);

  if ((await titleOf()) === null) throw new Error('expected a title to start with');
  await page.uncheck('#f-has-title');
  await page.waitForFunction(
    () => document.getElementById('cover-title').classList.contains('hidden'),
    undefined, { timeout: 10000 });
  console.log('5b. unticking the title hides it from the preview: true');
  await page.click('#btn-save');
  await settled();
  await page.waitForFunction(async (base) => {
    const r = await fetch(`${base}/api/v1/cover-designs?book_type=love`);
    const d = (await r.json()).designs.find((x) => x.slug === 'console-hearts');
    return d && !('title' in d);
  }, BASE, { timeout: 20000 });
  console.log('    and the saved design carries no title at all: true');

  // ...and ticking it back restores one, so this is a setting and not a
  // one-way door.
  await page.check('#f-has-title');
  await page.waitForFunction(
    () => !document.getElementById('cover-title').classList.contains('hidden'),
    undefined, { timeout: 10000 });
  await page.click('#btn-save');
  await settled();
  await page.waitForFunction(async (base) => {
    const r = await fetch(`${base}/api/v1/cover-designs?book_type=love`);
    const d = (await r.json()).designs.find((x) => x.slug === 'console-hearts');
    return d && 'title' in d;
  }, BASE, { timeout: 20000 });
  console.log('    ticking it back puts one there again: true');

  // 6. edit without re-uploading artwork
  await page.fill('#f-name', 'Console hearts v2');
  await page.click('#btn-save');
  await page.waitForFunction(
    () => [...document.querySelectorAll('.design-row b')]
      .some((b) => b.textContent === 'Console hearts v2'),
    undefined, { timeout: 20000 });
  console.log('6. renamed without re-uploading artwork: true');

  // 7. retire it — gone from the shop, still in the console
  page.once('dialog', (d) => d.accept());
  await page.click('#btn-retire');
  await page.waitForSelector('.design-row[data-slug="console-hearts"].retired',
                             { timeout: 20000 });
  const afterRetire = await page.evaluate(async (base) => {
    const r = await fetch(`${base}/api/v1/cover-designs?book_type=love`);
    return (await r.json()).designs.map((d) => d.slug);
  }, BASE);
  console.log('7. retired -> customers see:', afterRetire.join(', ') || '(none)');
  if (afterRetire.includes('console-hearts')) throw new Error('retire did not take');
  console.log('   still listed in the console for restoring: true');

  // 8. signing out forgets the token
  await page.click('#btn-signout');
  await page.waitForSelector('#screen-login.active');
  const stored = await page.evaluate(() => localStorage.getItem('mb-admin-token'));
  console.log('8. sign out cleared the token:', stored === null);
  if (stored) throw new Error('token survived sign out');

  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) throw new Error('page errors');
  console.log('ADMIN CONSOLE CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
