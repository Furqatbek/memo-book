const path = require('path');
const SHOTS = path.join(__dirname, '..', 'shots');
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 1360, height: 850 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));

  // --- themed type: travel ---
  await page.goto('http://127.0.0.1:8000/editor/');
  const tierHidden = await page.$eval('#tier-step', (el) => el.classList.contains('hidden'));
  console.log('tier step hidden until type chosen:', tierHidden);
  if (!tierHidden) throw new Error('tier step visible too early');

  // "change" goes back
  await page.click('.btype[data-btype="birthday"]');
  console.log('chosen label:', await page.$eval('#type-chosen', (el) => el.textContent));
  await page.click('#type-change');
  const backToTypes = !(await page.$eval('#type-step', (el) => el.classList.contains('hidden')));
  console.log('change link returns to type step:', backToTypes);

  await page.click('.btype[data-btype="travel"]');
  await page.click('.tier[data-tier="16"]');
  // A71 put a cover-design gallery between size and editor.
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'), undefined,
    { timeout: 30000 });
  // An occasion themes the COLOURS and nothing else. It used to prefill a
  // title too ("Our travels"), and words nobody asked for are exactly what
  // a customer then has to work out how to remove (A104). A book now starts
  // with no text on its cover whichever occasion it is.
  const titleBlocks = await page.$$('.cover-titles');
  const bg = await page.$eval('#page-canvas', (el) => el.style.background);
  console.log('travel cover title blocks:', titleBlocks.length, '| bg:', bg);
  if (titleBlocks.length !== 0) throw new Error('a new book must start with no text');
  if (!bg.includes('29, 77, 133')) throw new Error('themed bg missing'); // #1d4d85
  const creds = await page.evaluate(() => JSON.parse(localStorage.getItem('mb-book')));
  const book = await (await fetch(`http://127.0.0.1:8000/api/v1/books/${creds.book_id}`,
    { headers: { 'X-Edit-Token': creds.edit_token } })).json();
  console.log('server cover:', book.layout.cover.title, book.layout.cover.bg_color,
    book.layout.cover.title_color);
  if (book.layout.cover.title !== '') throw new Error('server has a title nobody typed');
  // The colour is still themed, so a title added later reads against this
  // background from the first character.
  if (book.layout.cover.bg_color !== '#1d4d85'
      || book.layout.cover.title_color !== '#ffffff') throw new Error('server layout not themed');
  await page.screenshot({ path: SHOTS + '/74-booktype-travel.png' });

  // --- neutral type: memory applies nothing ---
  await page.evaluate(() => localStorage.removeItem('mb-book'));
  await page.goto('http://127.0.0.1:8000/editor/');
  await page.click('.btype[data-btype="memory"]');
  await page.click('.tier[data-tier="16"]');
  // A71 put a cover-design gallery between size and editor.
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');
  // "memory" applies nothing at all — not even a colour, which is what
  // still separates it from the themed occasions now that none of them
  // bring text.
  const title2 = await page.$$('.cover-titles');
  const bg2 = await page.$eval('#page-canvas', (el) => el.style.background);
  console.log('memory cover title blocks:', title2.length, '| bg:', bg2);
  if (title2.length !== 0) throw new Error('memory must stay neutral');
  if (bg2.includes('29, 77, 133')) throw new Error('memory must not be themed');
  const addable = await page.evaluate(() =>
    !document.getElementById('btn-add-title').classList.contains('hidden'));
  console.log('and "+ Title" is offered:', addable);
  if (!addable) throw new Error('no way to add a title to a neutral cover');

  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) throw new Error('page errors');
  console.log('BOOK TYPE CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
