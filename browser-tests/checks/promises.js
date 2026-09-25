/* P1-1: two promises the business cannot keep as written.
 *
 * "What you see in the editor is what we print" is true of the LAYOUT and
 * cannot be true of the COLOUR. A screen emits light and paper reflects it,
 * so deep blues, bright greens and neon tones shift no matter what anyone
 * does — and phone screens are not calibrated to each other, let alone to
 * a press. Every photo-print business gets "the colours are different";
 * that sentence made it our fault by contract.
 *
 * "Printing defect? We reprint it free" is the right promise with no
 * boundary. Without one, a customer whose own 600px photo printed soft
 * calls it a printing defect and there is nothing to point at. At current
 * margins one avoidable reprint erases roughly twenty sales, so the policy
 * is a financial control, not legalese.
 *
 * The load-bearing assertions are that the unqualified sentence is gone
 * from every language, and that every free-reprint promise is within reach
 * of the boundary that defines it.
 *
 *   node checks/promises.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');
const path = require('path');

const BASE = 'http://127.0.0.1:8000';
const SHOTS = path.join(__dirname, '..', 'shots');
const PAGES = ['', 'ru/', 'uz/', 'uz-cyrl/', 'kaa/'];

/* The promise, in each language, as it used to read. None of these may
   survive anywhere on the page — it was translated, so checking only the
   English one would have found a fifth of it. */
const UNQUALIFIED = [
  /what you see in the editor is what we print/i,
  /что вы видите в редакторе, то мы и печатаем/i,
  /muharrirda nimani koʻrsangiz, biz aynan shuni chop etamiz/i,
  /муҳаррирда нимани кўрсангиз, биз айнан шуни чоп этамиз/i,
  /redaktorda neni kórseńiz, biz sonı basıp shıǵaramız/i,
];

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

(async () => {
  require('fs').mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  const errors = [];
  const noise = watchPage(page, errors);

  console.log('THE UNQUALIFIED COLOUR PROMISE IS GONE');
  for (const dir of PAGES) {
    await page.goto(`${BASE}/${dir}`);
    const text = await page.$eval('body', (el) => el.textContent.replace(/\s+/g, ' '));
    const survivor = UNQUALIFIED.find((re) => re.test(text));
    check(`${dir || 'en'}: nothing claims the print matches the screen`,
      !survivor, survivor ? String(survivor) : '');
  }

  console.log('AND WHAT REPLACED IT NAMES THE REASON');
  await page.goto(`${BASE}/`);
  const answer = await page.evaluate(() => {
    const d = [...document.querySelectorAll('#faq details')]
      .find((x) => /match what I designed/i.test(x.textContent));
    return d ? d.querySelector('p').textContent.replace(/\s+/g, ' ').trim() : '';
  });
  // The layout promise is kept — it is the half we can actually control.
  check('it still promises the layout', /same pages, same order, same text/i.test(answer),
    JSON.stringify(answer.slice(0, 60)));
  check('and explains why colour can differ',
    /screens? emit light/i.test(answer) && /paper reflects/i.test(answer));

  console.log('THE REPRINT POLICY EXISTS IN EVERY LANGUAGE');
  for (const dir of PAGES) {
    await page.goto(`${BASE}/${dir}#reprint`);
    await page.waitForTimeout(250);
    const policy = await page.evaluate(() => {
      const s = document.getElementById('reprint');
      if (!s) return null;
      return {
        covered: s.querySelectorAll('.policy-list.yes li').length,
        excluded: s.querySelectorAll('.policy-list.no li').length,
        claim: (s.querySelector('.policy-claim') || {}).textContent || '',
      };
    });
    check(`${dir || 'en'}: the policy is on the page`, !!policy);
    if (!policy) continue;
    // Both halves, or it is not a boundary. A list of what we cover with no
    // list of what we do not is the unbounded promise with extra words.
    check(`${dir || 'en'}: it says what is covered`, policy.covered >= 5,
      `${policy.covered}`);
    check(`${dir || 'en'}: and what is not`, policy.excluded >= 3,
      `${policy.excluded}`);
    check(`${dir || 'en'}: and gives a 14-day window`, /14/.test(policy.claim));
  }
  await page.goto(`${BASE}/#reprint`);
  await page.waitForTimeout(300);
  await page.$eval('#reprint', (el) => el.scrollIntoView());
  await page.screenshot({ path: `${SHOTS}/p11-reprint-policy.png` });

  console.log('AND EVERY FREE-REPRINT PROMISE CAN REACH IT');
  for (const dir of PAGES) {
    await page.goto(`${BASE}/${dir}`);
    const links = await page.$$eval('a[href="#reprint"]', (els) => els.length);
    // The perk, the FAQ answer and the footer. A promise that cannot reach
    // its own boundary is the promise this check exists to bound.
    check(`${dir || 'en'}: links to the policy`, links >= 3, `${links} links`);
  }

  console.log('AND THE LINK LANDS ON IT, NOT UNDER THE HEADER');
  await page.goto(`${BASE}/`);
  await page.click('a[href="#reprint"]');
  await page.waitForTimeout(600);
  const visible = await page.evaluate(() => {
    const h = document.querySelector('#reprint h2');
    if (!h) return false;
    const r = h.getBoundingClientRect();
    // Sticky header is ~64px; the heading must clear it.
    return r.top >= 60 && r.top < window.innerHeight;
  });
  check('the policy heading is on screen after following the link', visible);

  console.log('errors:', errors.length ? errors : 'none');
  if (noise.length) {
    console.log(`ignored ${noise.length} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`PROMISES CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('PROMISES CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
