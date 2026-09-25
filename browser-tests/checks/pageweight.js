/* P2-3: what the site costs someone on mobile data.
 *
 * The brief asked for WebP, lazy-loading and hard-compressed hero imagery.
 * Measured first, and the premise turned out not to hold: this site ships
 * NO raster images at all. Every illustration is inline SVG, the type is a
 * system stack, and there is not one <img> in the markup. There is nothing
 * to convert to WebP and nothing below the fold to defer.
 *
 * `assets/og.png` is 230 KB and is deliberately left alone: it is fetched
 * by Telegram's and Instagram's preview crawlers, never by the page, and
 * several of them do not render WebP — "optimising" it would cost the link
 * previews that P1-4 exists to produce, to save bytes no visitor downloads.
 *
 * So what is left worth checking is the thing the brief actually cares
 * about: first paint on a bad connection, and the weight staying down once
 * real photographs arrive. Both are measured here against a throttled
 * connection, with the dev server serving UNCOMPRESSED — production Caddy
 * gzips, so every number below is the pessimistic one.
 *
 *   node checks/pageweight.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');

const BASE = 'http://127.0.0.1:8000';
const PAGES = ['/', '/ru/', '/uz-cyrl/', '/kaa/', '/new-year/', '/ru/family/'];

// Chrome's "Fast 3G" numbers, used as a stand-in for a bad 4G cell: 4G in a
// Tashkent suburb at 7pm is not 4G in a laboratory.
const SLOW_4G = {
  offline: false,
  downloadThroughput: 1.6e6 / 8,
  uploadThroughput: 750e3 / 8,
  latency: 150,
};

const FCP_BUDGET_MS = 3000;   // the brief's target
const PAGE_BUDGET_KB = 120;   // uncompressed, matching scripts/launch_check.py

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

/* Wait for the entry rather than hoping it has been recorded: read too
   eagerly it comes back null, and a null that is treated as "fine" is a
   performance check that passes on a blank page. */
const FCP = `new Promise((resolve) => {
  const seen = performance.getEntriesByName('first-contentful-paint')[0];
  if (seen) return resolve(Math.round(seen.startTime));
  new PerformanceObserver((list, obs) => {
    for (const e of list.getEntries()) {
      if (e.name === 'first-contentful-paint') {
        obs.disconnect(); resolve(Math.round(e.startTime));
      }
    }
  }).observe({ type: 'paint', buffered: true });
  setTimeout(() => resolve(-1), 10000);
})`;

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  console.log(`ON A SLOW 4G CELL (uncompressed; production gzips)`);
  console.log('   page             reqs    bytes     FCP');

  for (const p of PAGES) {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const page = await ctx.newPage();
    const errors = [];
    watchPage(page, errors);
    const cdp = await ctx.newCDPSession(page);
    await cdp.send('Network.enable');
    await cdp.send('Network.emulateNetworkConditions', SLOW_4G);

    let bytes = 0, reqs = 0;
    cdp.on('Network.loadingFinished', (e) => { reqs++; bytes += e.encodedDataLength; });

    await page.goto(`${BASE}${p}`, { waitUntil: 'load' });
    const fcp = await page.evaluate(FCP);
    const kb = Math.round(bytes / 1024);
    console.log(`   ${p.padEnd(16)} ${String(reqs).padStart(4)} ${String(kb).padStart(6)} KB `
      + `${String(fcp).padStart(6)} ms`);

    check(`  ${p} paints inside ${FCP_BUDGET_MS}ms`, fcp > 0 && fcp < FCP_BUDGET_MS,
      `${fcp} ms`);
    check(`  ${p} stays under ${PAGE_BUDGET_KB} KB`, kb < PAGE_BUDGET_KB, `${kb} KB`);
    if (errors.length) check(`  ${p} loads without errors`, false, errors.join(' | '));
    await ctx.close();
  }

  console.log('\nAND NOTHING ON THESE PAGES IS A PHOTOGRAPH YET');
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  const types = [];
  page.on('response', (r) => types.push(r.headers()['content-type'] || ''));
  await page.goto(`${BASE}/`, { waitUntil: 'load' });
  const raster = types.filter((t) => /image\/(png|jpeg|gif|webp|avif)/.test(t));
  // Not a style rule: the moment this stops being true, the budget above is
  // the thing standing between the audience and a 2 MB page.
  check('  the home page downloads no raster image', raster.length === 0,
    raster.join(', '));
  const imgs = await page.evaluate(() => document.querySelectorAll('img').length);
  check('  and has no <img> element at all', imgs === 0, String(imgs));
  await ctx.close();

  await browser.close();
  if (failed) {
    console.error(`PAGE WEIGHT CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('PAGE WEIGHT CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
