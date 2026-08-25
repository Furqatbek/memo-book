/* A76: what the console shows when something on the money path is stuck.
 *
 * The data side is covered by tests/api/test_attention.py — eleven of them,
 * against a real database. What those cannot show is whether the operator
 * ever finds out, which is the entire point of the feature: the previous
 * answer was "a log line nobody reads".
 *
 * So this splits the job honestly:
 *
 *  - against the REAL endpoint: the panel stays invisible when nothing is
 *    wrong, and the live response has the shape the page reads.
 *  - against a STUBBED endpoint: each kind of problem renders correctly and
 *    clicking one opens that order.
 *
 * The stub is deliberate. Producing a genuinely abandoned outbox message
 * over HTTP would need a dev-only "break yourself" route, and adding
 * production API surface to make a test convenient is a bad trade — the
 * route would outlive the reason for it. The contract check above is what
 * ties the stub back to reality.
 *
 * Needs ADMIN_TOKEN (the dev server sets `dev-admin`).
 */
const { chromium } = require('playwright');
const path = require('path');
const SHOTS = path.join(__dirname, '..', 'shots');
const BASE = 'http://127.0.0.1:8000';
const TOKEN = 'dev-admin';

let failures = 0;
function check(label, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${label}${detail !== undefined ? `  ${detail}` : ''}`);
  if (!ok) failures++;
}

/* What the server sends for each kind, copied from what the service builds.
   If the server's shape moves, the contract check below fails first. */
const STUB = {
  count: 3,
  items: [
    { kind: 'render_failed', human_ref: 'UB-AAAA1', status: 'render_failed',
      customer_name: 'Aziza K', summary: 'the print files could not be rendered',
      detail: 'cover artwork is 3 pixels wide',
      action: 'Retry it, or cancel and refund.' },
    { kind: 'render_stalled', human_ref: 'UB-BBBB2', status: 'rendering',
      customer_name: 'Bek T', summary: 'rendering for over 30 minutes',
      detail: 'started 2026-08-25T07:00:00+00:00',
      action: 'The watchdog will move this to render_failed shortly.' },
    { kind: 'undelivered', human_ref: 'UB-CCCC3', status: null,
      customer_name: null,
      summary: "the printer was never sent this order's files",
      detail: 'telegram sendMessage failed: 401 unauthorized',
      action: 'Fix the cause, then use “Send to the printer again” on the order.' },
  ],
};

(async () => {
  const live = await fetch(`${BASE}/api/v1/admin/attention`,
    { headers: { 'X-Admin-Token': TOKEN } });
  if (!live.ok) {
    // Say which problem it is. "Is ADMIN_TOKEN set?" on a 429 sends you to
    // read the wrong config file.
    throw new Error(live.status === 429
      ? 'the admin API is rate-limiting this check — run it on its own, or '
        + 'raise RATE_LIMIT_ADMIN_PER_MIN (the dev server sets it high)'
      : `admin API refused "${TOKEN}" (${live.status}) — is ADMIN_TOKEN set?`);
  }
  const liveBody = await live.json();

  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1400, height: 950 } })).newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    // The click-through step answers 404 on purpose (see below), and the
    // browser logs every failed fetch. Anything else is a real error.
    if (m.type() === 'error' && !/404/.test(m.text())) {
      errors.push('console: ' + m.text());
    }
  });

  console.log('THE CONTRACT');
  check('the live endpoint answers with a count and a list',
    typeof liveBody.count === 'number' && Array.isArray(liveBody.items),
    JSON.stringify(liveBody).slice(0, 80));
  // Every key the page reads must exist on a real item. With an empty live
  // list there is nothing to compare, so this only runs when there is.
  if (liveBody.items.length) {
    const keys = Object.keys(liveBody.items[0]);
    const needed = ['kind', 'human_ref', 'summary', 'detail', 'action'];
    check('a real item carries every field the page renders',
      needed.every((k) => keys.includes(k)), JSON.stringify(keys));
  } else {
    console.log('   --    (live list is empty, so the stub carries the shape)');
  }

  console.log('WHEN NOTHING IS WRONG');
  await page.goto(`${BASE}/admin/`);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/admin/`);
  await page.fill('#login-token', TOKEN);
  await page.click('#login-form button[type=submit]');
  await page.waitForSelector('#screen-main.active', { timeout: 15000 });
  await page.waitForTimeout(1200);
  check('the panel stays invisible on a healthy system',
    !await page.isVisible('#attention'),
    `live count = ${liveBody.count}`);

  console.log('WHEN THINGS ARE STUCK');
  await page.route('**/api/v1/admin/attention', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify(STUB),
  }));
  // The panel's own "Re-check" button lives inside it, so it is unreachable
  // while it is hidden — by design. Refreshing the orders list re-checks
  // both, which is the path the operator actually has.
  await page.click('#btn-orders-refresh');
  await page.waitForSelector('#attention:not(.hidden)', { timeout: 15000 });
  check('and its own Re-check button is reachable once it is showing',
    await page.isVisible('#btn-attention-refresh'));

  const heading = (await page.textContent('#attention-count')).trim();
  check('it says how many things need a person', /3 things need you/.test(heading),
    JSON.stringify(heading));

  const rows = await page.$$eval('#attention-list li',
    (els) => els.map((e) => e.textContent.replace(/\s+/g, ' ').trim()));
  check('one row per problem', rows.length === 3, rows.length);
  check('a failed render names the order and the cause',
    rows[0].includes('UB-AAAA1') && rows[0].includes('3 pixels wide'));
  check('a stalled render says how long it has been stuck',
    rows[1].includes('over 30 minutes'));
  check('an abandoned message says the PRINTER never got the files',
    /printer/i.test(rows[2]) && /never/i.test(rows[2]),
    JSON.stringify(rows[2].slice(0, 60)));
  check('every row suggests what to do',
    rows.every((r) => /Retry|watchdog|again/i.test(r)));
  await page.screenshot({ path: SHOTS + '/96-attention.png' });

  console.log('CLICKING ONE');
  // The fix for every one of these lives on the order screen, so a row that
  // is not a way to get there is a dead end.
  let asked = null;
  await page.route('**/api/v1/admin/orders/UB-AAAA1', (route) => {
    asked = route.request().url();
    return route.fulfill({ status: 404, contentType: 'application/json',
                           body: '{"detail":"Not Found"}' });
  });
  await page.click('#attention-list li');
  await page.waitForTimeout(1200);
  check('clicking a row opens that order', !!asked && asked.includes('UB-AAAA1'),
    String(asked));

  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) throw new Error('page errors');
  if (failures) throw new Error(`${failures} checks failed`);
  console.log('ATTENTION CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
