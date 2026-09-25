/* P1-4: the link preview is the advertisement.
 *
 * Every marketing link gets pasted into Telegram or Instagram, and what
 * renders in that card is what people see before they see anything else.
 * With no tags they get a bare grey link — the same money spent, most of
 * the effect thrown away.
 *
 * The assertions that matter are not "the tags exist". They are:
 *
 *   - the IMAGE RESOLVES. A preview is fetched by somebody else's server,
 *     from a link with no page context, so a relative or broken og:image is
 *     the grey card with extra steps. It is fetched here and its bytes are
 *     measured.
 *   - the URL is THIS page's. Copying the block between language pages and
 *     forgetting og:url makes every share point at the English one.
 *   - the locales are DISTINCT, for the same reason.
 *
 *   node checks/ogtags.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');
const path = require('path');

const BASE = 'http://127.0.0.1:8000';
const SHOTS = path.join(__dirname, '..', 'shots');

const PAGES = [
  ['', 'https://rspixel.uz/', 'en_GB'],
  ['ru/', 'https://rspixel.uz/ru/', 'ru_RU'],
  ['uz/', 'https://rspixel.uz/uz/', 'uz_UZ'],
  ['uz-cyrl/', 'https://rspixel.uz/uz-cyrl/', 'uz_Cyrl_UZ'],
  ['kaa/', 'https://rspixel.uz/kaa/', 'kaa_UZ'],
];
const REQUIRED = ['og:title', 'og:description', 'og:image', 'og:url', 'og:locale'];

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

const meta = (page) => page.evaluate(() => {
  const out = {};
  for (const m of document.querySelectorAll('meta[property^="og:"]')) {
    out[m.getAttribute('property')] = m.getAttribute('content');
  }
  for (const m of document.querySelectorAll('meta[name^="twitter:"]')) {
    out[m.getAttribute('name')] = m.getAttribute('content');
  }
  out.__title = document.title;
  return out;
});

(async () => {
  require('fs').mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  const errors = [];
  const noise = watchPage(page, errors);

  const seenUrls = new Set();
  const seenLocales = new Set();
  let imageUrl = null;

  for (const [dir, url, locale] of PAGES) {
    console.log(`${dir || 'en'}`);
    await page.goto(`${BASE}/${dir}`);
    const m = await meta(page);

    const missing = REQUIRED.filter((k) => !m[k]);
    check('  every required tag is present', missing.length === 0, JSON.stringify(missing));
    check('  the card is a large image',
      m['twitter:card'] === 'summary_large_image', m['twitter:card']);

    // A title and description copied from the page, not invented for the
    // card — two places saying different things about the same product is
    // how one of them goes stale.
    check('  the title matches the page', m['og:title'] === m.__title,
      JSON.stringify([m['og:title'], m.__title].map((x) => (x || '').slice(0, 30))));
    check('  the description is not empty',
      (m['og:description'] || '').length > 60, `${(m['og:description'] || '').length} chars`);

    check('  og:url is this page', m['og:url'] === url, m['og:url']);
    check('  og:locale is this language', m['og:locale'] === locale, m['og:locale']);
    seenUrls.add(m['og:url']);
    seenLocales.add(m['og:locale']);

    check('  og:image is absolute', /^https?:\/\//.test(m['og:image'] || ''), m['og:image']);
    check('  and its size is declared',
      m['og:image:width'] === '1200' && m['og:image:height'] === '630',
      `${m['og:image:width']}x${m['og:image:height']}`);
    imageUrl = m['og:image'];
  }

  // Copying the block and forgetting to change these is the failure that
  // makes every language share the English page.
  check('the five pages each declare their own URL', seenUrls.size === 5,
    `${seenUrls.size} distinct`);
  check('and their own locale', seenLocales.size === 5, `${seenLocales.size} distinct`);

  console.log('AND THE IMAGE ACTUALLY EXISTS');
  // The tag can be perfect and the file absent; a preview server fetches it
  // and gives up quietly. Checked against the local copy of the same path.
  const local = `${BASE}${new URL(imageUrl).pathname}`;
  const res = await page.request.get(local);
  check('the og:image path serves a file', res.status() === 200, `${res.status()} ${local}`);
  const body = await res.body();
  check('and it is a PNG', body.slice(1, 4).toString() === 'PNG',
    JSON.stringify(body.slice(0, 8).toString('latin1')));
  // PNG header: width and height are big-endian at bytes 16..24.
  const w = body.readUInt32BE(16), h = body.readUInt32BE(20);
  check('at exactly 1200x630', w === 1200 && h === 630, `${w}x${h}`);
  // Telegram will not fetch an unreasonably large card.
  check('and small enough to be fetched', body.length < 5 * 1024 * 1024,
    `${(body.length / 1024).toFixed(0)} KB`);

  console.log('errors:', errors.length ? errors : 'none');
  if (noise.length) {
    console.log(`ignored ${noise.length} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`OG TAGS CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('OG TAGS CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
