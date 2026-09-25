/* Change 3: the funnel, driven through the real product.
 *
 * The unit tests prove each emission point in isolation. This proves the
 * thing that actually has to be true and that no unit test can show: one
 * person, one browser, one cookie — a click on an advert, and then a book
 * built step by step — arrives in the report as ONE funnel attributed to
 * the campaign that paid for the click.
 *
 * Everything below `site_visit` here is recorded by the server off its own
 * observations. The browser is never asked to report a book being started,
 * a photo landing, or a preview being rendered; if the instrumentation
 * only worked because the page told it what to think, this check would
 * still pass with the page lying, which is why those events are not the
 * page's to send.
 *
 *   node checks/funnel.js        (needs ADMIN_TOKEN=dev-admin)
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');
const path = require('path');

const BASE = 'http://127.0.0.1:8000';
const FIXTURES = path.join(__dirname, '..', 'fixtures');
const PHOTOS = [0, 1].map((n) => path.join(FIXTURES, `photo0${n}.jpg`));
const CAMPAIGN = `probe-${Date.now()}`;

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

const report = async (page) => (await (await page.request.get(
  `${BASE}/api/v1/internal/funnel?campaign=${CAMPAIGN}`,
  { headers: { 'X-Admin-Token': 'dev-admin' } })).json());

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  // One context for the whole journey: one cookie, one session, exactly as
  // a real customer would be.
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  const noise = watchPage(page, errors);

  console.log('A CLICK ON AN ADVERT');
  await page.goto(`${BASE}/new-year/?utm_source=instagram&utm_medium=cpc`
    + `&utm_campaign=${CAMPAIGN}`);
  await page.waitForTimeout(600);           // the beacon is fire-and-forget
  let r = await report(page);
  check('  the visit is recorded against the campaign', r.site_visit === 1,
    `site_visit=${r.site_visit}`);

  console.log('\nINTO THE EDITOR, AND A BOOK');
  await page.click('.hero-cta .btn-primary');
  await page.waitForSelector('.btype:not([disabled])', { timeout: 15000 });
  await page.waitForTimeout(400);
  r = await report(page);
  check('  the editor opening is recorded', r.editor_opened === 1,
    `editor_opened=${r.editor_opened}`);

  await page.click('.btype[data-btype="memory"]');
  await page.waitForSelector('.tier:not([disabled])', { timeout: 10000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active', { timeout: 15000 });
  r = await report(page);
  // Written by the server when the row was created — the page was not asked.
  check('  starting the book is recorded server-side', r.book_started === 1,
    `book_started=${r.book_started}`);

  console.log('\nPHOTOS, AND A LAYOUT');
  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('2 '),
    undefined, { timeout: 120000 });
  r = await report(page);
  check('  the first photo is recorded', r.first_photo_uploaded === 1,
    `first_photo_uploaded=${r.first_photo_uploaded}`);

  await page.click('#btn-autofill');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 30000 });
  r = await report(page);
  // Two photos across 32 pages is nowhere near half, so this must NOT fire.
  // A milestone that reports itself early is worse than one that is missing.
  check('  half_designed does NOT fire on a barely-started book',
    r.half_designed === 0, `half_designed=${r.half_designed}`);

  console.log('\nTHE WHOLE JOURNEY, UNDER ONE CAMPAIGN');
  r = await report(page);
  const c = r.by_campaign[CAMPAIGN];
  check('  the campaign has its own funnel', !!c, Object.keys(r.by_campaign).join(','));
  if (c) {
    check('    every step so far is attributed to it',
      c.counts.site_visit === 1 && c.counts.book_started === 1
      && c.counts.first_photo_uploaded === 1,
      JSON.stringify(c.counts));
    check('    and a conversion rate can be computed from it',
      c.conversion_rates.book_started_of_site_visit === 1.0,
      String(c.conversion_rates.book_started_of_site_visit));
  }

  console.log('\nA REFRESH DOES NOT INFLATE ANYTHING');
  const before = (await report(page)).book_started;
  await page.reload();
  await page.waitForTimeout(500);
  await page.reload();
  await page.waitForTimeout(500);
  const after = await report(page);
  check('  book_started is still one', after.book_started === before,
    `${before} -> ${after.book_started}`);
  // editor_opened is repeatable by design, but it counts DISTINCT SESSIONS,
  // so one person reloading twice must still read as one.
  check('  and editor_opened still counts one person', after.editor_opened === 1,
    `editor_opened=${after.editor_opened}`);

  console.log('\nerrors:', errors.length ? errors : 'none');
  if (noise.length) {
    console.log(`ignored ${noise.length} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`FUNNEL CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('FUNNEL CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
