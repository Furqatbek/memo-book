/* P2-1: the campaign landing pages.
 *
 * The main page is travel-locked — "Your trip. Your photos. Your book." —
 * and the next campaign is New Year gifting, which is family and
 * year-in-review. A visitor who clicks a New Year ad and lands on "Your
 * trip" has been told in the first second that they are in the wrong
 * place. So the travel page stays as specific as it is, and each campaign
 * gets its own page.
 *
 * What is worth checking in a browser rather than in the markup:
 *
 *   - /new-year WITHOUT a trailing slash resolves, because that is the
 *     form that goes in an ad, and a 404 there wastes the whole spend;
 *   - switching language STAYS ON THE CAMPAIGN. Sending a Russian speaker
 *     from the New Year page to the Russian home page is the very mismatch
 *     these pages exist to remove, one level down;
 *   - the auto-redirect carries the campaign too — an English ad link
 *     opened by someone whose browser is Russian must land on the Russian
 *     New Year page, not the Russian home page;
 *   - the CTA actually reaches the editor.
 *
 *   node checks/landings.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');
const path = require('path');

const BASE = 'http://127.0.0.1:8000';
const SHOTS = path.join(__dirname, '..', 'shots');
const DIRS = ['', 'ru/', 'uz/', 'uz-cyrl/', 'kaa/'];
const SLUGS = ['new-year', 'family'];
// Words that would mean the headline is still the travel one.
const TRAVEL = /\btrip\b|travel|поездк|путешеств|sayohat|саёҳат|sayaxat/i;

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

(async () => {
  require('fs').mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  const errors = [];
  const noise = watchPage(page, errors);

  console.log('EVERY PAGE, ON A PHONE');
  for (const slug of SLUGS) {
    for (const dir of DIRS) {
      const url = `${BASE}/${dir}${slug}/`;
      const resp = await page.goto(url);
      const info = await page.evaluate(() => ({
        h1: (document.querySelector('h1') || {}).textContent || '',
        samples: document.querySelectorAll('.badge-sample').length,
        overflow: document.documentElement.scrollWidth
          > document.documentElement.clientWidth + 1,
        cta: (document.querySelector('.hero-cta .btn-primary') || {})
          .getAttribute?.('href'),
      }));
      const label = `${dir || 'en'}${slug}`;
      const ok = resp.status() === 200 && info.h1.trim().length > 10
        && !TRAVEL.test(info.h1) && info.samples === 3 && !info.overflow;
      check(`  ${label.padEnd(18)} ${info.h1.trim().slice(0, 46)}`, ok,
        ok ? '' : JSON.stringify({ status: resp.status(), ...info }));
    }
  }

  console.log('\nTHE FORM THAT GOES IN AN AD');
  for (const u of ['/new-year', '/family', '/ru/new-year']) {
    const resp = await page.goto(`${BASE}${u}`);
    check(`  ${u} resolves`, resp.status() === 200
      && page.url().endsWith(`${u}/`), `${resp.status()} ${page.url()}`);
  }

  console.log('\nSWITCHING LANGUAGE STAYS ON THE CAMPAIGN');
  await page.goto(`${BASE}/new-year/`);
  await page.click('.site-footer a[hreflang="ru"]');
  await page.waitForURL(/\/ru\/new-year\//, { timeout: 10000 }).catch(() => {});
  check('  English New Year -> Russian New Year', /\/ru\/new-year\/$/.test(page.url()),
    page.url());
  const ruH1 = (await page.textContent('h1')).trim();
  check('  and the headline is the Russian one', /[А-Яа-я]/.test(ruH1), ruH1.slice(0, 46));

  await page.goto(`${BASE}/kaa/family/`);
  await page.click('.site-footer a[hreflang="uz"]');
  await page.waitForURL(/\/uz\/family\//, { timeout: 10000 }).catch(() => {});
  check('  Karakalpak family -> Uzbek family', /\/uz\/family\/$/.test(page.url()),
    page.url());

  console.log('\nAND SO DOES THE AUTOMATIC ONE');
  /* The ad link is the English one. A Russian-speaking visitor gets sent to
     their language on arrival — and must land on the CAMPAIGN, not the home
     page, which is what the old data-root-only redirect would have done. */
  const fresh = await browser.newContext({
    viewport: { width: 390, height: 844 }, locale: 'ru-RU',
  });
  const visitor = await fresh.newPage();
  await visitor.goto(`${BASE}/new-year/`);
  await visitor.waitForURL(/\/ru\//, { timeout: 10000 }).catch(() => {});
  check('  a Russian browser opening /new-year/ lands on /ru/new-year/',
    /\/ru\/new-year\/$/.test(visitor.url()), visitor.url());
  await fresh.close();

  console.log('\nTHE CTA REACHES THE EDITOR');
  await page.goto(`${BASE}/new-year/`);
  await page.click('.hero-cta .btn-primary');
  await page.waitForURL(/\/editor\//, { timeout: 15000 }).catch(() => {});
  check('  from the New Year page', /\/editor\/$/.test(page.url()), page.url());
  await page.goto(`${BASE}/ru/family/`);
  await page.click('.hero-cta .btn-primary');
  await page.waitForURL(/\/editor\//, { timeout: 15000 }).catch(() => {});
  check('  and from a translated one', /\/editor\/$/.test(page.url()), page.url());

  await page.goto(`${BASE}/new-year/`);
  await page.screenshot({ path: path.join(SHOTS, 'landing-new-year.png'), fullPage: true });
  await page.goto(`${BASE}/kaa/family/`);
  await page.screenshot({ path: path.join(SHOTS, 'landing-kaa-family.png'), fullPage: true });

  console.log('\nerrors:', errors.length ? errors : 'none');
  if (noise.length) {
    console.log(`ignored ${noise.length} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`LANDING PAGES CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('LANDING PAGES CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
