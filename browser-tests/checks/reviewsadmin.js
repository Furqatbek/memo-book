/* CR-003-9: the Reviews tab in the admin console.
 *
 * The page exists because `GET /api/v1/admin/reviews` was JSON-only, and
 * that is the one endpoint whose absence actively blocked something: you
 * cannot copy an approved review into `assets/reviews.js` without reading
 * it first.
 *
 * What is asserted is the honesty contract, not the layout. Three rules
 * govern reviews and the page has to make all three hard to break:
 *
 *   never publish without the permission box — so a review that did not
 *   grant it gets no snippet and no copy button at all, not a greyed-out
 *   one somebody presses anyway;
 *
 *   never edit a review's wording — so the text is shown in full with the
 *   line breaks they typed, because a review displayed as a flattened
 *   fragment is one somebody tidies before pasting;
 *
 *   never invent one — so a snippet pasted UNEDITED must publish nothing.
 *   That is checked against `usable()` from assets/reviews.js itself rather
 *   than against a copy of the rule, because a copy drifts.
 *
 * The rows are served through a route intercept. Reaching a real submitted
 * review needs an order walked to `delivered`, seven days of waiting and a
 * form submission; and a fixture review living in the repository is an
 * invented review, which is the practice this product refuses. The same
 * reasoning as checks/reviewslot.js.
 *
 *   node checks/reviewsadmin.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');

const BASE = 'http://127.0.0.1:8000';
const TOKEN = 'dev-admin';

/* Two rows, and the second is the one that matters: somebody who wrote
   something useful and did NOT agree to be quoted. */
const ROWS = {
  reviews: [
    {
      human_ref: 'UB-AAAAA',
      submitted_at: '2026-09-20T10:00:00Z',
      text: 'Книга получилась очень красивая, спасибо!\n\n'
        + 'Доставка немного задержалась, но это мелочь.',
      display_name: "Aziza K. O'g'li",   // an apostrophe, on purpose
      city: 'Tashkent',
      lang: 'ru',
      may_publish: true,
      photo_url: null,
    },
    {
      human_ref: 'UB-BBBBB',
      submitted_at: '2026-09-21T10:00:00Z',
      text: 'Muqova biroz egilgan holda keldi.',
      display_name: 'Bek',
      city: null,
      lang: 'uz',
      may_publish: false,
      photo_url: null,
    },
  ],
  publishing: 'copy an approved review into assets/reviews.js by hand, word '
    + 'for word. Never publish one without may_publish.',
};

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({
    viewport: { width: 1360, height: 900 },
    permissions: ['clipboard-read', 'clipboard-write'],
  })).newPage();
  const errors = [];
  const noise = watchPage(page, errors);

  await page.route('**/api/v1/admin/reviews', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify(ROWS),
  }));

  await page.goto(`${BASE}/admin/`);
  await page.waitForSelector('#screen-login.active', { timeout: 15000 });
  await page.fill('#login-token', TOKEN);
  await page.click('#login-form button[type=submit]');
  await page.waitForSelector('#screen-main:not(.hidden)', { timeout: 20000 });
  // The sign-in refusal path is not exercised here, so nothing above should
  // have logged anything.
  errors.length = 0;

  console.log('THE TAB EXISTS AND LOADS ON ARRIVAL');
  check('there is a Reviews tab', await page.isVisible('.tab[data-tab="reviews"]'));
  await page.click('.tab[data-tab="reviews"]');
  await page.waitForSelector('#rv-list .rv-row', { timeout: 20000 });
  const rows = await page.$$eval('#rv-list .rv-row', (els) => els.map((el) => ({
    private: el.classList.contains('rv-private'),
    pill: (el.querySelector('.status-pill') || {}).textContent.trim(),
    text: (el.querySelector('.rv-text') || {}).textContent,
    snippet: el.querySelector('.rv-snippet')
      ? el.querySelector('.rv-snippet').textContent : null,
    copyButtons: [...el.querySelectorAll('button')]
      .filter((b) => /copy/i.test(b.textContent)).length,
  })));
  check('both reviews are listed', rows.length === 2, String(rows.length));

  const approved = rows.find((r) => !r.private);
  const priv = rows.find((r) => r.private);

  console.log('\nPERMISSION DECIDES EVERYTHING');
  check('the approved one is marked so', approved && approved.pill === 'May publish',
    approved && approved.pill);
  check('the other is marked private', priv && priv.pill === 'Private',
    priv && priv.pill);
  check('and gets NO snippet', priv && priv.snippet === null);
  check('and NO copy button', priv && priv.copyButtons === 0,
    priv && String(priv.copyButtons));
  check('the approved one gets both',
    approved && approved.snippet !== null && approved.copyButtons === 1);

  console.log('\nTHE WORDS ARE SHOWN AS WRITTEN');
  check('the paragraph break survives on screen',
    approved && /\n\n/.test(approved.text), JSON.stringify(approved && approved.text));
  check('nothing is truncated',
    approved && approved.text.includes('это мелочь'));

  console.log('\nAN UNEDITED PASTE PUBLISHES NOTHING');
  /* Judged by reviews.js's OWN rule, fetched from the site rather than
     copied here — a copied rule is one that drifts from the thing that
     actually decides. */
  const verdict = await page.evaluate(async (snippet) => {
    const src = await (await fetch('/assets/reviews.js')).text();
    const m = /function usable\(r\) \{\s*return ([^;]+);/.exec(src);
    if (!m) return { error: 'could not find usable() in assets/reviews.js' };
    // eslint-disable-next-line no-new-func
    const usable = new Function('r', `return ${m[1]};`);
    let entry;
    try {
      // eslint-disable-next-line no-eval
      entry = eval(`[${snippet.replace(/,\s*$/, '')}]`)[0];
    } catch (e) {
      return { error: `the snippet is not valid JavaScript: ${e.message}` };
    }
    return {
      rule: m[1].trim(),
      parsed: true,
      wouldPublish: !!usable(entry),
      name: entry.name,
      textKeepsBreaks: /\n\n/.test(entry.text || ''),
    };
  }, approved && approved.snippet);

  if (verdict.error) {
    check(verdict.error, false);
  } else {
    console.log(`   reviews.js rule: ${verdict.rule}`);
    check('the snippet is valid JavaScript', verdict.parsed);
    check('an apostrophe in their name does not break the file',
      verdict.name && verdict.name.includes("'"), verdict.name);
    check('pasted unedited it would NOT publish', verdict.wouldPublish === false,
      `wouldPublish=${verdict.wouldPublish}`);
    check('and their paragraph breaks survive the quoting',
      verdict.textKeepsBreaks);
  }

  console.log('\nCOPY PUTS THE SAME THING ON THE CLIPBOARD');
  await page.click('#rv-list .rv-row:not(.rv-private) button');
  await page.waitForTimeout(500);
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  check('the clipboard matches what is shown', clip.trim() === approved.snippet.trim(),
    `${clip.length} vs ${approved.snippet.length} chars`);

  console.log('\nerrors:', errors.length ? errors : 'none');
  if (noise.length) {
    console.log(`ignored ${noise.length} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`REVIEWS ADMIN CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('REVIEWS ADMIN CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
