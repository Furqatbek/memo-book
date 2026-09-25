/* P2-4: the privacy policy and the terms, and the links that reach them.
 *
 * Customers upload photographs of their families and the site said nothing
 * about what happens to them. That is a trust gap on its own, and a
 * payment acquirer will ask for both documents before approving an
 * account.
 *
 * The assertion that matters most is not that the pages exist — it is that
 * the FOOTER LINK ON EVERY PAGE ACTUALLY REACHES THEM. A privacy link that
 * 404s is worse than no link: it is the P0-2 failure, on the page a
 * customer opens at the exact moment they have started to doubt you.
 *
 * Every page is followed from its own footer rather than by constructing
 * the URL here, because a relative href that resolves correctly from
 * `/index.html` and wrongly from `/ru/new-year/` is precisely the bug a
 * hand-written URL would hide.
 *
 *   node checks/policies.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');
const path = require('path');

const BASE = 'http://127.0.0.1:8000';
const SHOTS = path.join(__dirname, '..', 'shots');
const DIRS = ['', 'ru/', 'uz/', 'uz-cyrl/', 'kaa/'];
// Every page that carries a Support column, in every language.
const FROM = [...DIRS, ...DIRS.map((d) => `${d}new-year/`), ...DIRS.map((d) => `${d}family/`)];

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

(async () => {
  require('fs').mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({
    viewport: { width: 390, height: 844 },
  })).newPage();
  const errors = [];
  const noise = watchPage(page, errors);

  console.log('BOTH DOCUMENTS, EVERY LANGUAGE, ON A PHONE');
  for (const slug of ['privacy', 'terms']) {
    for (const dir of DIRS) {
      const resp = await page.goto(`${BASE}/${dir}${slug}/`);
      const info = await page.evaluate(() => ({
        h1: (document.querySelector('h1') || {}).textContent || '',
        sections: document.querySelectorAll('.policy-doc h2').length,
        words: (document.querySelector('.policy-doc') || { textContent: '' })
          .textContent.trim().split(/\s+/).length,
        overflow: document.documentElement.scrollWidth
          > document.documentElement.clientWidth + 1,
      }));
      const ok = resp.status() === 200 && info.sections >= 5
        && info.words > 150 && !info.overflow;
      check(`  ${(dir + slug).padEnd(18)} ${info.sections} sections, ${info.words} words`,
        ok, ok ? '' : JSON.stringify({ status: resp.status(), ...info }));
    }
  }

  console.log('\nTHE FOOTER LINK REACHES THEM, FROM EVERY PAGE');
  for (const from of FROM) {
    await page.goto(`${BASE}/${from}`);
    const hrefs = await page.evaluate(() => {
      const out = {};
      for (const a of document.querySelectorAll('.site-footer a')) {
        const h = a.getAttribute('href') || '';
        if (/privacy\/$/.test(h)) out.privacy = a.href;
        if (/terms\/$/.test(h)) out.terms = a.href;
      }
      return out;
    });
    if (!hrefs.privacy || !hrefs.terms) {
      check(`  ${from || 'en'} links to both documents`, false, JSON.stringify(hrefs));
      continue;
    }
    // Follow them, rather than trusting the href to be well-formed.
    const p = await page.request.get(hrefs.privacy);
    const t = await page.request.get(hrefs.terms);
    check(`  ${(from || 'en').padEnd(18)} -> privacy ${p.status()}, terms ${t.status()}`,
      p.status() === 200 && t.status() === 200,
      `${hrefs.privacy} ${hrefs.terms}`);
  }

  console.log('\nAND THE TWO DOCUMENTS REACH EACH OTHER');
  for (const dir of ['', 'ru/']) {
    await page.goto(`${BASE}/${dir}privacy/`);
    await page.click('.site-nav a[href$="terms/"]');
    await page.waitForURL(/terms\/$/, { timeout: 10000 }).catch(() => {});
    check(`  ${dir || 'en'}privacy -> terms`, /terms\/$/.test(page.url()), page.url());
  }

  console.log('\nTHE POLICY SAYS THE THING THE ENGINEERING DOES');
  await page.goto(`${BASE}/privacy/`);
  const body = (await page.textContent('.policy-doc')).toLowerCase();
  // Verified against a GPS-tagged fixture in tests/test_exif_privacy.py —
  // this asserts the customer is actually told about it.
  check('  it tells the customer the coordinates are removed',
    body.includes('coordinates'), '');
  check('  it names the 30-day retention', body.includes('30 days'), '');
  check('  it says who else sees the photographs',
    body.includes('print shop'), '');
  await page.screenshot({ path: path.join(SHOTS, 'privacy.png'), fullPage: true });

  console.log('\nerrors:', errors.length ? errors : 'none');
  if (noise.length) {
    console.log(`ignored ${noise.length} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`POLICY PAGES CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('POLICY PAGES CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
