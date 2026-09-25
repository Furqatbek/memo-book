/* CR-003-7, CR-003-8: the countdown and the places counter, in a browser.
 *
 * The banner is a promise about a printer's schedule, so what this check
 * is really testing is restraint:
 *
 *   - with a campaign configured, the sentence appears and the number in
 *     it comes from the SERVER, not from the browser's clock;
 *   - with NO ceiling configured, no places figure is shown at all. Not
 *     zero, not "limited places" — nothing. A fabricated scarcity counter
 *     is the one thing this product refuses to do, and the shape of the
 *     payload is what makes inventing one impossible rather than merely
 *     discouraged.
 *
 * Needs a dev server started with a campaign:
 *
 *   CAMPAIGN_DEADLINE=2099-12-31 CAMPAIGN_LABEL="New Year" \
 *   PRODUCTION_DAYS=14 python scripts/devserver.py
 *
 *   node checks/campaign.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');

const BASE = 'http://127.0.0.1:8000';

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({
    viewport: { width: 390, height: 844 },
  })).newPage();
  const errors = [];
  const noise = watchPage(page, errors);

  console.log('WHAT THE SERVER SAYS');
  const api = await (await page.request.get(`${BASE}/api/v1/campaign`)).json();
  const c = api.campaign;
  if (!c) {
    console.log('   no campaign configured on this server — start it with');
    console.log('   CAMPAIGN_DEADLINE=2099-12-31 CAMPAIGN_LABEL="New Year" \\');
    console.log('   PRODUCTION_DAYS=14 python scripts/devserver.py');
    await browser.close();
    process.exit(2);
  }
  check('  it carries an order-by date, not just the deadline',
    !!c.order_by && c.order_by !== c.deadline, `${c.order_by} vs ${c.deadline}`);
  check('  and a whole number of days', Number.isInteger(c.days_left),
    String(c.days_left));

  console.log('\nTHE BANNER IN THE EDITOR');
  await page.goto(`${BASE}/editor/`);
  await page.waitForSelector('.btype:not([disabled])', { timeout: 15000 });
  await page.click('.btype[data-btype="memory"]');
  await page.waitForSelector('.tier:not([disabled])', { timeout: 10000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active', { timeout: 15000 });
  await page.waitForSelector('#campaign-banner:not(.hidden)', { timeout: 15000 });

  const text = (await page.textContent('#campaign-banner')).trim();
  console.log(`   banner: ${text}`);
  check('  it names the campaign', text.includes(c.label), text);
  check('  and counts the days the SERVER counted',
    text.includes(String(c.days_left)) || /last day/i.test(text), text);

  console.log('\nAND SAYS NOTHING IT CANNOT COMPUTE');
  const hasPlaces = Object.prototype.hasOwnProperty.call(c, 'places_left');
  if (!hasPlaces) {
    // The default, and the one that matters: no ceiling configured.
    check('  no places figure in the payload', true, 'MONTHLY_CAPACITY unset');
    check('  and none on the screen',
      !/place|left|remaining/i.test(text), text);
  } else {
    check('  the places figure is a real number',
      Number.isInteger(c.places_left) && Number.isInteger(c.capacity),
      `${c.places_left}/${c.capacity}`);
    check('  and never exceeds the ceiling', c.places_left <= c.capacity,
      `${c.places_left}/${c.capacity}`);
    check('  the screen shows the same number',
      text.includes(String(c.places_left)), text);
  }

  console.log('\nerrors:', errors.length ? errors : 'none');
  if (noise.length) {
    console.log(`ignored ${noise.length} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`CAMPAIGN CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('CAMPAIGN CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
