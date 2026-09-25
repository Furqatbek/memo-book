/* A105: the front page says you already have a book.
 *
 * The editor has always had a resume card, but on its own start screen —
 * you only saw it after deciding to open the editor. Somebody who left a
 * book half-finished and came back to the site was met by "Create your
 * book" and nothing else, the same page a first-time visitor sees. Their
 * book was safe in this browser's localStorage and the site gave them no
 * reason to believe it.
 *
 * What the banner must not do is promise something it cannot keep, so most
 * of this check is about when it stays hidden: a browser with no book, a
 * book the server no longer has, and a book that has been ordered and can
 * no longer be edited.
 *
 * Needs the dev server to be serving the site at `/`, which it now does
 * because production does — Caddy puts site, editor and API on one
 * hostname, and this feature only works because of that.
 *
 *   node checks/resumebanner.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');
const path = require('path');

const BASE = 'http://127.0.0.1:8000';
const SHOTS = path.join(__dirname, '..', 'shots');

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

/* Only what is actually ON SCREEN, row by row. The banner's markup is in
   the page whether or not it is shown, so reading it unconditionally
   returns text nobody can see — which would let every assertion about the
   wording pass against a hidden banner. Reading the CONTAINER is not enough
   either, now that it holds two rows with their own `hidden`: a visible
   book row would drag the hidden order row's words in with it, and an
   assertion about the wording would be reading half a banner that is not
   there. */
const bannerText = (page) => page.$eval('#resume-banner', (el) => {
  if (el.hidden) return '';
  return [...el.querySelectorAll('.resume-row')]
    .filter((row) => !row.hidden)
    .map((row) => row.textContent.replace(/\s+/g, ' ').trim())
    .join(' | ');
}).catch(() => '');

async function makeBook(page, tier) {
  await page.goto(`${BASE}/editor/`);
  await page.click('.btype[data-btype="travel"]');
  await page.waitForFunction(
    () => document.querySelector('[data-tier-pages]').textContent,
    undefined, { timeout: 30000 });
  await page.click(`.tier[data-tier="${tier}"]`);
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 30000 });
  return page.evaluate(() => JSON.parse(localStorage.getItem('mb-book')));
}

(async () => {
  require('fs').mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  const errors = [];
  const noise = watchPage(page, errors);

  console.log('A FIRST-TIME VISITOR SEES NOTHING NEW');
  await page.goto(`${BASE}/`);
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.waitForTimeout(600);
  check('the banner is hidden with no book', await page.isHidden('#resume-banner'));

  console.log('AND SOMEBODY WITH A BOOK IS TOLD SO');
  const creds = await makeBook(page, 32);
  await page.goto(`${BASE}/`);
  const shown = await page.waitForSelector('#resume-banner:not([hidden])', { timeout: 15000 })
    .then(() => true).catch(() => false);
  check('the banner appears on the front page', shown);
  const text = await bannerText(page);
  // 32 sheets is a 64-page book: the number makes it THEIR book rather than
  // a generic nag, so it has to be the real one.
  check('and it names the book', text.includes('64'), JSON.stringify(text));
  check('and says where the book is kept', /browser/i.test(text), JSON.stringify(text));
  await page.screenshot({ path: `${SHOTS}/105-resume-banner.png`,
                          clip: { x: 0, y: 0, width: 1280, height: 200 } });

  console.log('AND THE BUTTON REALLY OPENS THAT BOOK');
  await page.click('#resume-link');
  await page.waitForSelector('#btn-resume, #screen-editor.active', { timeout: 30000 });
  if (await page.isVisible('#btn-resume')) await page.click('#btn-resume');
  await page.waitForSelector('#screen-editor.active', { timeout: 30000 });
  const opened = await page.evaluate(() => JSON.parse(localStorage.getItem('mb-book')));
  check('the editor opened the same book', opened.book_id === creds.book_id,
    `${opened.book_id} vs ${creds.book_id}`);

  console.log('A BOOK THE SERVER NO LONGER HAS IS NOT OFFERED');
  // Credentials outlive the book they point at — books expire. Offering to
  // continue something that is gone is worse than saying nothing.
  await page.goto(`${BASE}/`);
  await page.evaluate(() => localStorage.setItem('mb-book', JSON.stringify(
    { book_id: '00000000-0000-4000-8000-000000000000', edit_token: 'nope' })));
  await page.reload();
  await page.waitForTimeout(1200);
  check('the banner stays hidden', await page.isHidden('#resume-banner'));
  const cleared = await page.evaluate(() => localStorage.getItem('mb-book'));
  check('and the dead credentials are thrown away', cleared === null,
    JSON.stringify(cleared));

  console.log('NOR IS A BOOK THAT HAS ALREADY BEEN ORDERED');
  // Past `draft` the book is locked, and "continue where you left off"
  // would be an invitation to a screen that no longer takes changes. The
  // status is faked here rather than by buying a book: what is under test
  // is OUR decision, not the checkout.
  await page.route('**/api/v1/books/**', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ book_id: 'x', status: 'pending_payment', page_count: 64 }),
  }));
  await page.evaluate(() => localStorage.setItem('mb-book', JSON.stringify(
    { book_id: '11111111-1111-4111-8111-111111111111', edit_token: 't' })));
  await page.reload();
  await page.waitForTimeout(1200);
  check('an ordered book gets no "continue"', await page.isHidden('#resume-banner'));
  await page.unroute('**/api/v1/books/**');

  console.log('AN ORDER ON ITS WAY IS OFFERED FOR TRACKING');
  /* Stubbed rather than bought. That a REAL checkout leaves `mb-order` in
     the shape this reads is the one thing a stub cannot prove, so `e2e`
     proves it — it pays for a whole order already. What is under test here
     is the decision: which statuses are worth a banner. */
  const stubStatus = (status) => page.route('**/api/v1/orders/**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json',
                    body: JSON.stringify({ human_ref: 'UB-TRACK', status }) }));
  const putOrder = () => page.evaluate(() => {
    localStorage.setItem('mb-order', JSON.stringify(
      { ref: 'UB-TRACK', phone: '+998 90 123-45-67', status: 'pending_payment' }));
    sessionStorage.clear();
  });

  await page.goto(`${BASE}/`);
  await page.evaluate(() => localStorage.clear());
  await stubStatus('sent_to_production');
  await putOrder();
  await page.reload();
  const orderShown = await page.waitForSelector('#order-row:not([hidden])', { timeout: 15000 })
    .then(() => true).catch(() => false);
  check('an order in flight gets a banner', orderShown);
  const orderText = await page.$eval('#order-row',
    (el) => (el.hidden ? '' : el.textContent.replace(/\s+/g, ' ').trim())).catch(() => '');
  check('and it names the order', orderText.includes('UB-TRACK'),
    JSON.stringify(orderText));
  check('and points at the order screen',
    (await page.$eval('#order-link', (el) => el.getAttribute('href'))) === 'editor/#order');
  await page.screenshot({ path: `${SHOTS}/105-order-banner.png`,
                          clip: { x: 0, y: 0, width: 1280, height: 200 } });

  console.log('AND A FINISHED ONE IS NOT');
  // A banner that goes on asking after the book has arrived is a nag.
  for (const done of ['delivered', 'cancelled', 'refunded']) {
    await page.unroute('**/api/v1/orders/**');
    await stubStatus(done);
    await putOrder();
    await page.reload();
    await page.waitForTimeout(900);
    check(`${done}: no banner`, await page.isHidden('#order-row'));
  }

  console.log('AND THE STATUS IS ASKED FOR ONCE A SESSION, NOT ONCE A PAGE');
  // The endpoint takes the customer's phone in the query string, so every
  // extra call writes their number into an access log again.
  await page.unroute('**/api/v1/orders/**');
  let asks = 0;
  await page.route('**/api/v1/orders/**', (route) => {
    asks += 1;
    return route.fulfill({ status: 200, contentType: 'application/json',
                           body: JSON.stringify({ human_ref: 'UB-TRACK', status: 'shipped' }) });
  });
  await putOrder();
  await page.reload();
  await page.waitForSelector('#order-row:not([hidden])', { timeout: 15000 });
  await page.reload();
  await page.waitForSelector('#order-row:not([hidden])', { timeout: 15000 });
  await page.reload();
  await page.waitForTimeout(900);
  check('three page loads, one request', asks === 1, `${asks} requests`);
  check('and the banner still shows from what was cached',
    await page.isVisible('#order-row'));
  await page.unroute('**/api/v1/orders/**');
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });

  console.log('AND IT WORKS ON A LANGUAGE PAGE, ONE LEVEL DOWN');
  await page.goto(`${BASE}/editor/`);
  await makeBook(page, 16);
  await page.goto(`${BASE}/ru/`);
  await page.waitForSelector('#resume-banner:not([hidden])', { timeout: 15000 });
  const ru = await bannerText(page);
  check('the Russian page shows it', ru.length > 0, JSON.stringify(ru));
  check('translated, not left in English', !/your book/i.test(ru), JSON.stringify(ru));
  // `editor/` from /ru/ would be /ru/editor/, which does not exist.
  const href = await page.$eval('#resume-link', (el) => el.getAttribute('href'));
  check('and its link climbs out of the language folder', href === '../editor/', href);
  await page.click('#resume-link');
  await page.waitForSelector('#btn-resume, #screen-editor.active, .btype', { timeout: 30000 });
  check('which lands on the editor', page.url().includes('/editor/'), page.url());

  console.log('errors:', errors.length ? errors : 'none');
  if (noise.length) {
    console.log(`ignored ${noise.length} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`RESUME BANNER CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('RESUME BANNER CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
