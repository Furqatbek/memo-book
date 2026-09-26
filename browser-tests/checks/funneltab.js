/* Change 3: the funnel on screen.
 *
 * `GET /api/v1/internal/funnel` has existed since Change 3 and was read with
 * curl. Putting it on a page is only an improvement if the page keeps the two
 * things the payload is careful about, because a chart is exactly where they
 * get lost:
 *
 *   THE TOP OF THE FUNNEL IS CLIENT-REPORTED. An ad-blocker eats some of
 *   those rows, so it is a floor and not a count, and every rate measured
 *   against it reads better than it is. The payload says which steps those
 *   are; the page must say it too — and must say it about the steps the
 *   PAYLOAD names, not about a list typed into the frontend that can drift
 *   away from what is actually being counted. That is why the fixture below
 *   marks a fourth step as client-reported: if the caveat is derived, the
 *   page says so without anybody editing it.
 *
 *   A ZERO DENOMINATOR IS "NO DATA", NOT 0%. Nobody arrived and nobody
 *   converted are different facts. `_rates` answers `null` for the first and
 *   `0.0` for the second, and the page has to keep them apart.
 *
 * The third thing is subtler and is the reason the fixture has no site
 * visits at all: because the top is under-counted, a step below can legally
 * be BIGGER than the step above it. A tidier chart would render that as a
 * negative drop-off or clamp it to zero — either of which buries the only
 * signal we get that rows are missing.
 *
 * Served through a route intercept. A real funnel with ten populated steps
 * needs a paid order, and this check is about the rendering of a payload
 * whose shape is already covered by the backend's own tests.
 *
 *   node checks/funneltab.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');

const BASE = 'http://127.0.0.1:8000';
const TOKEN = 'dev-admin';

/* The ten steps, in FUNNEL_ORDER, and the counts are chosen to put all
   three hard cases in one payload:
     site_visit 0        -> every "of the top" rate is null      ("no data")
     book_started 6 > editor_opened 4 -> a step over 100%
     payment_succeeded 0 out of 1     -> a genuine zero          ("0%") */
const COUNTS = {
  site_visit: 0,
  editor_opened: 4,
  book_started: 6,
  first_photo_uploaded: 5,
  half_designed: 3,
  design_completed: 2,
  preview_viewed: 2,
  checkout_opened: 1,
  checkout_submitted: 1,
  payment_succeeded: 0,
};
const STEPS = Object.keys(COUNTS);

/* Computed the way backend/app/api/funnel.py:_rates computes them, including
   `null` for a zero denominator — the point of the check is the rendering of
   a faithful payload. */
function rates(counts) {
  const out = {};
  const top = counts[STEPS[0]] || 0;
  let previous = null;
  for (const key of STEPS) {
    const n = counts[key] || 0;
    if (previous) {
      out[`${previous[0]}_to_${key}`] =
        previous[1] ? Number((n / previous[1]).toFixed(4)) : null;
    }
    out[`${key}_of_site_visit`] = top ? Number((n / top).toFixed(4)) : null;
    previous = [key, n];
  }
  return out;
}

const IG = { ...COUNTS, editor_opened: 3, book_started: 4, site_visit: 9,
             payment_succeeded: 0 };
const TG = { ...COUNTS, editor_opened: 1, book_started: 2, site_visit: 4,
             checkout_submitted: 1, payment_succeeded: 1 };

// Every step at zero: a window in which genuinely nothing happened, which is
// what the console shows on the day it is deployed.
const NOTHING = Object.fromEntries(STEPS.map((k) => [k, 0]));

function payload({ from = null, to = null, campaign = null, empty = false } = {}) {
  const counts = empty ? NOTHING : COUNTS;
  const all = empty ? {} : { ig_sept: IG, tg_channel: TG };
  const by = {};
  for (const [name, c] of Object.entries(all)) {
    if (campaign && name !== campaign) continue;
    by[name] = { counts: c, conversion_rates: rates(c) };
  }
  return {
    ...counts,
    conversion_rates: rates(counts),
    by_campaign: by,
    window: { from, to, campaign },
    // Three of these match production. `preview_viewed` does NOT: it is here
    // so that a caveat which merely repeats a hardcoded list fails.
    counting: {
      site_visit: 'distinct sessions, client-reported',
      editor_opened: 'distinct sessions, client-reported',
      checkout_opened: 'distinct books, client-reported',
      preview_viewed: 'distinct books, client-reported',
      everything_else: 'distinct books, server-observed',
    },
  };
}

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({
    viewport: { width: 1360, height: 900 },
  })).newPage();
  const errors = [];
  const noise = watchPage(page, errors);

  const asked = [];
  let empty = false;   // flipped at the end, for the nothing-happened window
  await page.route('**/api/v1/internal/funnel*', (route) => {
    const url = new URL(route.request().url());
    asked.push(url.search);
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(payload({
        from: url.searchParams.get('from'),
        to: url.searchParams.get('to'),
        campaign: url.searchParams.get('campaign'),
        empty,
      })),
    });
  });

  await page.goto(`${BASE}/admin/`);
  await page.waitForSelector('#screen-login.active', { timeout: 15000 });
  await page.fill('#login-token', TOKEN);
  await page.click('#login-form button[type=submit]');
  await page.waitForSelector('#screen-main:not(.hidden)', { timeout: 20000 });
  errors.length = 0;

  console.log('THE TAB EXISTS AND LOADS ON ARRIVAL');
  check('there is a Funnel tab', await page.isVisible('.tab[data-tab="funnel"]'));
  await page.click('.tab[data-tab="funnel"]');
  await page.waitForSelector('#fn-steps .fn-step', { timeout: 20000 });
  check('it asked the report endpoint once', asked.length === 1,
    JSON.stringify(asked));

  const rows = await page.$$eval('#fn-steps .fn-step', (els) => els.map((el) => ({
    label: el.querySelector('b').textContent,
    n: el.querySelector('.fn-n').textContent,
    ofTop: el.querySelector('.fn-line .muted').textContent,
    width: el.querySelector('.fn-fill').style.width,
    drop: el.querySelector('.fn-bar + .muted')
      ? el.querySelector('.fn-bar + .muted').textContent : null,
  })));

  console.log('\nEVERY STEP IN THE SERVER’S ORDER');
  check('ten steps are drawn', rows.length === 10, String(rows.length));
  check('the first is the site visit', rows[0] && rows[0].label === 'Saw the site',
    rows[0] && rows[0].label);
  check('the last is a payment', rows[9] && rows[9].label === 'Paid',
    rows[9] && rows[9].label);
  check('the counts are the payload’s',
    rows.map((r) => r.n).join(',') === Object.values(COUNTS).join(','),
    rows.map((r) => r.n).join(','));
  check('the top step has no drop-off line above it', rows[0].drop === null);

  console.log('\nNO DATA IS NOT ZERO');
  /* Every "of the top" rate is null here, because nothing reported a site
     visit. Not one of them may read as a percentage. */
  const pcts = rows.filter((r) => !/no data/.test(r.ofTop));
  check('with no site visits, every share-of-top says "no data"',
    pcts.length === 0, pcts.map((r) => `${r.label}: ${r.ofTop}`).join('; '));
  check('and no bar claims a width', rows.every((r) => r.width === '0%'),
    rows.map((r) => r.width).join(','));
  check('nothing rendered NaN or Infinity',
    !/NaN|Infinity/.test(rows.map((r) => `${r.ofTop}${r.width}${r.drop}`).join('')));
  check('the step nobody reached says so, not 0%',
    /no data/i.test(rows[1].drop) && !/0%/.test(rows[1].drop), rows[1].drop);
  /* Not "0.0%", which is what a small-number formatter would produce, and
     not "no data": a real zero has to look different from an absence. */
  check('but a REAL zero says 0%',
    /(^|\s)0% /.test(rows[9].drop) && !/no data/i.test(rows[9].drop),
    rows[9].drop);
  check('and names the people who stopped',
    /1 person stopped here/.test(rows[9].drop), rows[9].drop);

  console.log('\nA STEP BIGGER THAN THE ONE ABOVE IT IS SAID OUT LOUD');
  check('the 150% step is not clamped', /150%/.test(rows[2].drop), rows[2].drop);
  check('it is not rendered as a negative drop-off',
    !/-\d/.test(rows[2].drop), rows[2].drop);
  check('it blames the under-count above it',
    /under-counted/.test(rows[2].drop), rows[2].drop);

  console.log('\nTHE CAVEAT IS READ OFF THE PAYLOAD, NOT TYPED IN');
  const caveat = await page.textContent('#fn-caveat');
  console.log(`   "${caveat}"`);
  for (const label of ['Saw the site', 'Opened the editor', 'Opened checkout']) {
    check(`it names ${label}`, caveat.includes(label));
  }
  check('it names the fourth step THIS payload calls client-reported',
    caveat.includes('Looked at the preview'),
    'a caveat repeating a hardcoded list would miss this');
  check('it does not name a server-observed step',
    !caveat.includes('Paid'), caveat);
  check('it says which direction the error runs',
    /floor and not a count/.test(caveat));
  check('it says a missing rate reads "no data"', /no data/.test(caveat));
  check('it says the window is all time', /all time/.test(caveat));
  check('it warns that the dates are UTC', /UTC/.test(caveat));

  console.log('\nPER CAMPAIGN, WHICH IS WHAT THE COUNTING IS FOR');
  check('the campaign table is shown',
    await page.isVisible('#fn-campaigns'));
  const head = await page.$$eval('#fn-ch-head th', (els) =>
    els.map((el) => el.textContent));
  check('one column per step, plus the name and the paid rate',
    head.length === 12, `${head.length}: ${head.join(' | ')}`);
  /* The number the table exists to produce comes SECOND, beside the name:
     ten step columns do not fit a screen, and it was off the right edge. */
  check('the paid rate is the second column, not the twelfth',
    head[1] === 'Paid / saw the site', head[1]);
  const table = await page.$$eval('#fn-ch-body tr', (trs) => trs.map((tr) =>
    [...tr.querySelectorAll('td')].map((td) => td.textContent)));
  check('a row per campaign', table.length === 2, JSON.stringify(table));
  const ig = table.find((r) => r[0] === 'ig_sept');
  check('ig_sept’s counts are its own',
    ig && ig[2] === '9' && ig[4] === '4', ig && ig.join(','));
  check('its paid rate is 0% — it has visits, so this is a real zero',
    ig && ig[1] === '0%', ig && ig[1]);
  const tg = table.find((r) => r[0] === 'tg_channel');
  check('tg_channel converted 1 of 4', tg && tg[1] === '25%', tg && tg[1]);

  console.log('\nTHE FILTERS REFETCH, AND THE PICKER SURVIVES BEING USED');
  const options = await page.$$eval('#fn-campaign option', (els) =>
    els.map((el) => el.value));
  check('the picker lists both campaigns and an All',
    options.length === 3 && options[0] === '', JSON.stringify(options));
  await page.selectOption('#fn-campaign', 'ig_sept');
  await page.waitForFunction(
    () => document.querySelectorAll('#fn-ch-body tr').length === 1,
    null, { timeout: 10000 });
  check('choosing one asks the server for it',
    /campaign=ig_sept/.test(asked[asked.length - 1]), asked[asked.length - 1]);
  const after = await page.$$eval('#fn-campaign option', (els) =>
    els.map((el) => el.value));
  check('the picker still offers the way back',
    after.length === 3 && after.includes('tg_channel'), JSON.stringify(after));
  check('and keeps the chosen campaign selected',
    (await page.inputValue('#fn-campaign')) === 'ig_sept');

  await page.selectOption('#fn-campaign', '');
  await page.waitForFunction(
    () => document.querySelectorAll('#fn-ch-body tr').length === 2,
    null, { timeout: 10000 });
  await page.fill('#fn-from', '2026-09-01');
  await page.fill('#fn-to', '2026-09-20');
  const before = asked.length;
  await page.click('#fn-refresh');
  // Waited on the request the intercept actually saw, not on a timer: a
  // sleep long enough to be reliable is a sleep long enough to hide a
  // Refresh button that fired nothing.
  for (let i = 0; i < 100 && asked.length === before; i++) {
    await page.waitForTimeout(100);
  }
  check('Refresh actually asks again', asked.length > before,
    `${before} -> ${asked.length}`);
  const last = asked[asked.length - 1];
  check('the window goes out as asked', /from=2026-09-01/.test(last), last);
  /* The server compares occurred_at <= to. A bare date would cut the last
     day off at midnight and silently drop everything in it. */
  check('and the last day is included to its end',
    /to=2026-09-20T23%3A59%3A59|to=2026-09-20T23:59:59/.test(last), last);
  /* The caveat reports the window the SERVER echoed back, not what is in the
     two inputs — the server is the one that parsed them. So this waits for
     the re-render rather than reading straight after the request: a timeout
     here is a genuine failure and reported as one. */
  const rendered = await page.waitForFunction(
    () => !/all time/.test(document.getElementById('fn-caveat').textContent),
    null, { timeout: 10000 }).then(() => true).catch(() => false);
  const shownWindow = await page.textContent('#fn-caveat');
  check('the caveat reports the window the server echoed back', rendered,
    shownWindow.slice(0, 90));

  console.log('\nA WINDOW WHERE NOTHING HAPPENED SAYS SO ONCE');
  /* Ten zeroes and nine identical "nobody reached the step above" lines are
     less informative than one sentence, and they read as a broken page
     rather than an empty one. */
  empty = true;
  await page.click('#fn-refresh');
  const wentEmpty = await page.waitForFunction(
    () => !document.getElementById('fn-empty').classList.contains('hidden'),
    null, { timeout: 10000 }).then(() => true).catch(() => false);
  check('the empty note appears', wentEmpty);
  check('and the ten zero steps are hidden with it',
    await page.isHidden('#fn-steps'));
  check('and so is the campaign table', await page.isHidden('#fn-campaigns'));
  check('but the caveat stays, because it is about the counting',
    (await page.textContent('#fn-caveat')).includes('client-reported')
    || /reported by the browser/.test(await page.textContent('#fn-caveat')));

  console.log('\nerrors:', errors.length ? errors : 'none');
  if (noise.length) {
    console.log(`ignored ${noise.length} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`FUNNEL TAB CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('FUNNEL TAB CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
