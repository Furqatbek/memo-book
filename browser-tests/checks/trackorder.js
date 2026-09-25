/* P0-2: "Track an order" has to land on tracking an order.
 *
 * The site's Support column pointed at `editor/`, so a customer chasing an
 * order they had already paid for arrived at "What kind of book are you
 * making?" — with the way to their order a scroll below the fold, on a
 * screen that reads as the wrong page entirely.
 *
 * The lookup was not missing. It existed, it worked, and nothing linked to
 * it. That is the failure worth remembering: a feature nobody can reach is
 * indistinguishable from a feature nobody built, and it is more expensive,
 * because it looks finished from the inside.
 *
 * The assertion that matters is that following the link from the site puts
 * a REFERENCE AND PHONE FORM in front of the customer. Landing on the
 * editor at all is not enough — that was the bug.
 *
 *   node checks/trackorder.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');
const path = require('path');

const BASE = 'http://127.0.0.1:8000';
const SHOTS = path.join(__dirname, '..', 'shots');
// Every language's Support column, and the word it uses for tracking.
const PAGES = [['', 'editor/#track'], ['ru/', '../editor/#track'],
               ['uz/', '../editor/#track'], ['uz-cyrl/', '../editor/#track'],
               ['kaa/', '../editor/#track']];

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

const onLookup = (page) => page.evaluate(() => {
  const form = document.getElementById('or-lookup');
  const screen = document.getElementById('screen-order');
  return !!form && !form.classList.contains('hidden')
    && !!screen && screen.classList.contains('active');
});

(async () => {
  require('fs').mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  const errors = [];
  const noise = watchPage(page, errors);

  console.log('THE LINK GOES STRAIGHT TO THE LOOKUP');
  await page.goto(`${BASE}/editor/`);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/editor/#track`);
  await page.waitForSelector('#screen-order.active', { timeout: 15000 });
  check('the order screen opens, not the book picker', await onLookup(page));
  // The bug was landing on the editor *at all*, so name what must NOT be on
  // screen as well as what must.
  check('and the "what kind of book" step is not what they see',
    await page.isHidden('#screen-start'));
  const fields = await page.$$eval('#or-lookup [name]', (els) => els.map((e) => e.name));
  check('it asks for a reference and a phone',
    fields.includes('ref') && fields.includes('phone'), JSON.stringify(fields));
  await page.screenshot({ path: `${SHOTS}/p02-track-lookup.png` });

  console.log('AND THE FORM REALLY ASKS THE SERVER');
  await page.fill('#or-lookup [name=ref]', 'UB-NOPE1');
  await page.fill('#or-lookup [name=phone]', '+998 90 000 00 00');
  await page.click('#or-lookup button[type=submit]');
  const toast = await page.waitForSelector('.toast, [class*=toast]', { timeout: 15000 })
    .then((el) => el.textContent()).catch(() => '');
  check('an unknown order is refused in words a customer can read',
    toast.trim().length > 0 && !/error|undefined/i.test(toast),
    JSON.stringify(toast.trim()));
  check('and it did not silently show somebody an order', await onLookup(page));

  console.log('FROM EVERY LANGUAGE`S SUPPORT COLUMN');
  for (const [dir, href] of PAGES) {
    await page.goto(`${BASE}/${dir}`);
    const link = await page.$(`a[href="${href}"]`);
    check(`${dir || 'en'}: the Support column links to the lookup`, !!link, href);
    if (!link) continue;
    await link.click();
    await page.waitForSelector('#screen-order.active', { timeout: 15000 });
    check(`${dir || 'en'}: and it lands there`, await onLookup(page));
  }

  console.log('AND `#order` FALLS BACK TO IT ON A DEVICE THAT HAS NO ORDER');
  // The customer who ordered on their phone and is now looking on a laptop.
  // Sending them to the book picker would be the same bug in a second place.
  await page.goto(`${BASE}/editor/`);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/editor/#order`);
  await page.waitForSelector('#screen-order.active', { timeout: 15000 });
  check('a stored-order link with nothing stored offers the lookup',
    await onLookup(page));

  console.log('errors:', errors.length ? errors : 'none');
  if (noise.length) {
    console.log(`ignored ${noise.length} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`TRACK ORDER CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('TRACK ORDER CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
