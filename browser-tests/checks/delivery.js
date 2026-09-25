/* P1-6: a buyer outside Tashkent can find out that we reach them.
 *
 * "Do you even deliver here?" is the first question someone in Namangan or
 * Nukus asks, and at 11pm there is nobody to ask it to. An unanswered one
 * is a closed tab, and nobody ever hears that they tried — which is what
 * makes this the cheapest sentence on the page to have missing.
 *
 * So it has to be in two places, and both are asserted separately:
 *
 *   - the FAQ, where somebody looking for it goes to look. The answer is
 *     read AFTER expanding the entry, because a <details> that opens onto
 *     nothing is exactly the failure a source-level check cannot see;
 *   - the footer, where somebody who never thought to ask still passes it.
 *
 * Visible text only — an element the page never shows is not an answer.
 *
 *   node checks/delivery.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');
const path = require('path');

const BASE = 'http://127.0.0.1:8000';
const SHOTS = path.join(__dirname, '..', 'shots');

// [dir, the coverage claim, the FAQ question that leads to it]
const PAGES = [
  ['', /deliver anywhere in Uzbekistan/i, /where do you deliver/i],
  ['ru/', /любую точку Узбекистана/i, /куда вы доставляете/i],
  ['uz/', /istalgan nuqtasiga yetkazib/i, /qayerga yetkazib berasiz/i],
  ['uz-cyrl/', /исталган нуқтасига етказиб/i, /қаерга етказиб берасиз/i],
  ['kaa/', /qálegen jerine jetkerip/i, /qay jerge jetkerip beresiz/i],
];

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

/* Text the page actually shows. An element with no layout box is not an
   answer to anything, so it does not count towards one. */
const visibleText = (page, selector) => page.evaluate((sel) => {
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden') {
      out.push(el.textContent.trim());
    }
  }
  return out.join(' · ');
}, selector);

(async () => {
  require('fs').mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({
    viewport: { width: 390, height: 844 },   // the phone, because most are
  })).newPage();
  const errors = [];
  const noise = watchPage(page, errors);

  for (const [dir, claim, question] of PAGES) {
    console.log(`\n${dir || 'en'}`);
    await page.goto(`${BASE}/${dir}`);

    // ---- the FAQ ----
    const summaries = await page.$$('.faq-list details summary');
    let entry = null;
    for (const s of summaries) {
      if (question.test((await s.textContent()).trim())) { entry = s; break; }
    }
    check('  the FAQ asks where we deliver', !!entry);
    if (entry) {
      check('  and the question is visible without opening anything',
        await entry.isVisible());
      await entry.click();
      const answer = await page.evaluate((q) => {
        for (const d of document.querySelectorAll('.faq-list details')) {
          if (!d.open) continue;
          const s = d.querySelector('summary');
          if (s && new RegExp(q, 'i').test(s.textContent)) {
            const p = d.querySelector('p');
            const r = p.getBoundingClientRect();
            return (r.width > 0 && r.height > 0) ? p.textContent.trim() : '';
          }
        }
        return '';
      }, question.source);
      // A <details> that opens onto nothing reads as an answer in the source
      // and as silence on the page.
      check('  opening it shows the coverage', claim.test(answer),
        answer.slice(0, 90) || '(nothing visible)');
    }

    // ---- the footer ----
    const foot = await visibleText(page, 'footer.site-footer p, footer.site-footer a');
    check('  the footer states it too', claim.test(foot),
      (foot.match(claim) || ['not found'])[0]);
  }

  // The brief singled this page out: its readers are furthest from the
  // print shop and likeliest to assume the answer is no.
  console.log('\nTHE KARAKALPAK PAGE NAMES KARAKALPAKSTAN');
  await page.goto(`${BASE}/kaa/`);
  const kaaSummaries = await page.$$('.faq-list details summary');
  for (const s of kaaSummaries) {
    if (/qay jerge jetkerip beresiz/i.test((await s.textContent()).trim())) {
      await s.click();
      break;
    }
  }
  const kaaAnswer = await visibleText(page, '.faq-list details[open] p');
  check('it says Qaraqalpaqstan in so many words',
    /Qaraqalpaqstan/i.test(kaaAnswer), kaaAnswer.slice(0, 90));

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth
    > document.documentElement.clientWidth + 1);
  check('and the page still has no sideways scroll on a phone', !overflow);
  await page.screenshot({ path: path.join(SHOTS, 'delivery-kaa.png'), fullPage: false });

  console.log('\nerrors:', errors.length ? errors : 'none');
  if (noise.length) {
    console.log(`ignored ${noise.length} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`DELIVERY CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('DELIVERY CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
