/* P1-3: the reviews section holds real reviews, or says it has none.
 *
 * The copy that sits there now — "Verified reviews from our first customers
 * will appear here… We never publish invented quotes" — is the honest
 * thing to show while the pilot books are printing, and it converts an
 * empty section into a statement. What it needed was the component behind
 * it: a slot that takes a name, a photograph and what the book was about,
 * and that looks deliberate with three entries rather than sparse.
 *
 * Both states are checked, because both are shipped states. The empty one
 * is the one on the site today, and it must not quietly turn into an empty
 * grid; the filled one is what the founder gets the moment three customers
 * have spoken, and it must not render half-built cards.
 *
 * The reviews are served through a route intercept rather than written into
 * the repository. There are no real reviews yet, and a fixture review is an
 * invented review living in the codebase — exactly the thing this section
 * exists not to do.
 *
 *   node checks/reviewslot.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:8000';
const SHOTS = path.join(__dirname, '..', 'shots');
const SOURCE = path.join(__dirname, '..', '..', 'assets', 'reviews.js');
const EMPTY_MARK = '    // Nothing yet. The pilot books are still being printed.';

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

const THREE = `
    { name: 'Aziza K.', city: 'Tashkent', photo: 'reviews/a.jpg', lang: 'ru',
      book: '64 pages · a year in Samarkand', text: 'Книга приехала лучше, чем я ожидала.' },
    { name: 'Bekzod R.', city: 'Nukus', photo: 'reviews/b.jpg', lang: 'uz',
      book: '32 pages · our wedding', text: 'Bir kechada tayyor boʻldi.' },
    { name: 'Dilnoza S.', city: 'Samarkand', photo: 'reviews/c.jpg', lang: 'ru',
      book: '96 pages · a year of family', text: 'Заказала для мамы на юбилей.' },`;

// One good entry and one missing its `book`, to prove a half-built review
// is dropped rather than shown.
const BROKEN = THREE + `
    { name: 'Nobody', photo: 'reviews/d.jpg', text: 'no book field' },`;

async function serve(page, entries) {
  const src = fs.readFileSync(SOURCE, 'utf8');
  if (!src.includes(EMPTY_MARK)) throw new Error('reviews.js no longer has its empty marker');
  await page.unroute('**/assets/reviews.js').catch(() => {});
  await page.route('**/assets/reviews.js', (route) => route.fulfill({
    status: 200, contentType: 'application/javascript',
    body: src.replace(EMPTY_MARK, entries),
  }));
  await page.unroute('**/assets/reviews/*').catch(() => {});
  await page.route('**/assets/reviews/*', (route) => route.fulfill({
    status: 200, contentType: 'image/jpeg',
    body: fs.readFileSync(path.join(__dirname, '..', 'fixtures', 'photo00.jpg')),
  }));
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 1000 } })).newPage();
  const errors = [];
  const noise = watchPage(page, errors);

  console.log('WITH NO REVIEWS, THE HONEST NOTE STANDS');
  for (const dir of ['', 'ru/', 'uz/', 'uz-cyrl/', 'kaa/']) {
    await page.goto(`${BASE}/${dir}`);
    await page.waitForTimeout(350);
    const state = await page.evaluate(() => ({
      note: !!document.querySelector('.reviews-note')
        && !document.querySelector('.reviews-note').hidden,
      grid: !!document.getElementById('reviews')
        && !document.getElementById('reviews').hidden,
      cards: document.querySelectorAll('.review-card').length,
    }));
    check(`${dir || 'en'}: the note is shown and the grid is not`,
      state.note && !state.grid && state.cards === 0, JSON.stringify(state));
  }
  // The load-bearing one: nothing on the page pretends to be a customer.
  const invented = await page.evaluate(() =>
    document.querySelectorAll('.review-card, .review-photo').length);
  check('and no card claims to be anybody', invented === 0, `${invented}`);

  console.log('AND THE NOTE SAYS WHY, RATHER THAN LOOKING BROKEN');
  await page.goto(`${BASE}/`);
  const note = await page.$eval('.reviews-note', (el) => el.textContent.replace(/\s+/g, ' '));
  check('it promises verified reviews', /verified reviews/i.test(note));
  check('and states the rule', /never publish invented quotes/i.test(note));

  console.log('WITH THREE, IT LOOKS DELIBERATE');
  await serve(page, THREE);
  await page.goto(`${BASE}/`);
  await page.waitForSelector('#reviews:not([hidden])', { timeout: 10000 });
  check('three cards render', (await page.$$('.review-card')).length === 3);
  check('and the note steps aside', await page.isHidden('.reviews-note'));
  const card = await page.evaluate(() => {
    const c = document.querySelector('.review-card');
    return {
      photo: !!c.querySelector('.review-photo'),
      name: (c.querySelector('.review-name') || {}).textContent || '',
      book: (c.querySelector('.review-book') || {}).textContent || '',
      lang: (c.querySelector('.review-text') || {}).getAttribute
        ? c.querySelector('.review-text').getAttribute('lang') : null,
    };
  });
  // Name, photograph, and what the book was about — the three things asked
  // for, on every card.
  check('each card has a photograph', card.photo);
  check('a name', card.name.includes('Aziza'), JSON.stringify(card.name));
  check('and what the book was about', /pages/.test(card.book), JSON.stringify(card.book));
  // The words stay in the language they were written in; translating a
  // customer's sentence is putting words in their mouth.
  check('and the quote is marked with its own language', card.lang === 'ru', `${card.lang}`);

  const widths = await page.$$eval('.review-card', (els) =>
    els.map((e) => Math.round(e.getBoundingClientRect().width)));
  check('the three share a row evenly', new Set(widths).size === 1,
    JSON.stringify(widths));
  await page.screenshot({ path: `${SHOTS}/p13-reviews-three.png` });

  console.log('AND A HALF-BUILT ENTRY IS DROPPED, NOT SHOWN');
  // A card with a name and no book is indistinguishable from one somebody
  // invented in a hurry.
  await serve(page, BROKEN);
  await page.goto(`${BASE}/`);
  await page.waitForSelector('#reviews:not([hidden])', { timeout: 10000 });
  const names = await page.$$eval('.review-name', (els) => els.map((e) => e.textContent));
  check('the incomplete one does not appear', !names.some((n) => /Nobody/.test(n)),
    JSON.stringify(names));
  check('and the complete ones still do', names.length === 3, `${names.length}`);

  console.log('AND FEWER THAN THREE KEEPS THE NOTE');
  await serve(page, THREE.split('},')[0] + '} ,');
  await page.goto(`${BASE}/`);
  await page.waitForTimeout(500);
  check('one review does not become a lonely row',
    await page.isHidden('#reviews') && await page.isVisible('.reviews-note'));

  console.log('errors:', errors.length ? errors : 'none');
  if (noise.length) {
    console.log(`ignored ${noise.length} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`REVIEW SLOT CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('REVIEW SLOT CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
