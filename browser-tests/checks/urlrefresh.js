/* A99: an image whose signed URL has gone stale must recover itself.
 *
 * Photos and cover artwork are shown from presigned storage URLs with a
 * deadline in them. The page asks for those once and holds them, so a long
 * enough sitting leaves the browser with credentials that aged out in its
 * hand — nothing fails server-side, the images just stop loading.
 *
 * The fix is one capture-phase `error` listener that asks for fresh URLs and
 * redraws. The thing that makes it a fix rather than a new bug is the
 * guards: an object that is genuinely gone fails EVERY time, and a refresh
 * per failure would be an endless loop pointed at our own API. So the
 * interesting assertion here is not "it recovers" — it is "twenty broken
 * images still cause exactly one re-fetch".
 *
 *   node checks/urlrefresh.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');
const path = require('path');
const BASE = 'http://127.0.0.1:8000';
const SHOTS = path.join(__dirname, '..', 'shots');
const PHOTOS = [0, 1, 2, 3].map(
  (i) => path.join(__dirname, '..', 'fixtures', `photo0${i}.jpg`));

const SIGNED = /[?&](Expires|X-Amz-Signature)=/;
const PHOTOS_API = /\/api\/v1\/books\/[^/]+\/photos(\?|$)/;

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* Broken signed images the customer can actually see, named rather than
   counted — a survivor here means some visible surface is not redrawn by the
   refresh, and the class says which.

   VISIBLE is the right scope. The start screen's design gallery stays in the
   DOM behind the editor, and it is not redrawn by the refresh — it does not
   need to be. It clears itself and re-fetches the catalogue every time it is
   shown, so what a customer sees there is always freshly built. Asserting
   over hidden DOM would be asserting something nobody can observe. */
async function brokenVisible(page) {
  return page.evaluate(() => [...document.querySelectorAll('img')]
    .filter((i) => i.offsetParent !== null
      && i.complete && i.naturalWidth === 0
      && /[?&](Expires|X-Amz-Signature)=/.test(i.getAttribute('src') || ''))
    .map((i) => `${i.className || '(no class)'} in ${i.parentElement
      && i.parentElement.className}`));
}

/* Re-request every signed image on the page, which is what a browser does
   when it redraws — and what fails once the URLs have aged out. */
async function breakImages(page, n) {
  return page.evaluate((limit) => {
    const imgs = [...document.querySelectorAll('img')].filter(
      (i) => /[?&](Expires|X-Amz-Signature)=/.test(i.getAttribute('src') || ''));
    let hit = 0;
    for (const img of imgs) {
      if (hit >= limit) break;
      // A different URL each time, so the browser cannot answer from cache
      // and every one of these really goes to the network.
      img.src = `${img.getAttribute('src')}&stale=${Date.now()}-${hit}`;
      hit += 1;
    }
    return hit;
  }, n);
}

(async () => {
  require('fs').mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  const errs = [];
  const noise = watchPage(page, errs);

  await page.goto(`${BASE}/editor/`);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/editor/`);
  await page.click('.btype[data-btype="memory"]');
  await page.waitForFunction(
    () => document.querySelector('[data-tier-pages]').textContent,
    undefined, { timeout: 30000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');
  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('4 '),
    undefined, { timeout: 180000 });
  await page.click('#btn-autofill');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 60000 });

  // Only now start counting: uploading calls the photos endpoint on its own.
  let blockImages = true;
  let photoFetches = 0;
  await page.route('**/*', (route) => {
    const url = route.request().url();
    if (SIGNED.test(url)) {
      // Exactly what an expired signature looks like to an <img>.
      if (blockImages) return route.abort('failed');
      return route.continue();
    }
    if (PHOTOS_API.test(url)) {
      photoFetches += 1;
      // The refresh is under way. Storage works again from here, so the
      // redraw that follows loads the fresh URLs — which is the real
      // sequence: the URLs had expired, not the bucket gone missing.
      blockImages = false;
    }
    return route.continue();
  });

  console.log('ONE STALE IMAGE ASKS FOR FRESH URLS');
  const brokeOne = await breakImages(page, 1);
  check('an image was made to fail', brokeOne === 1, `${brokeOne}`);
  for (let i = 0; i < 40 && photoFetches === 0; i += 1) await sleep(250);
  check('the editor re-fetched the photo URLs', photoFetches === 1,
    `${photoFetches} fetches`);
  await page.screenshot({ path: `${SHOTS}/99-stale.png` });

  console.log('AND THE IMAGES COME BACK BY THEMSELVES');
  // No reload, no button: the refresh redrew them.
  for (let i = 0; i < 40; i += 1) {
    if ((await brokenVisible(page)).length === 0) break;
    await sleep(250);
  }
  const broken = await brokenVisible(page);
  check('no visible signed image is left broken', broken.length === 0,
    JSON.stringify(broken));
  await page.screenshot({ path: `${SHOTS}/99-recovered.png` });

  console.log('AND A GENUINELY DEAD IMAGE DOES NOT BECOME A LOOP');
  // Everything below fails for a reason no refresh can fix. If the guard
  // were missing, each failure would ask the API for fresh URLs and each
  // redraw would fail again — a loop pointed at our own server.
  blockImages = true;
  const before = photoFetches;
  const brokeMany = await breakImages(page, 20);
  await sleep(4000);
  check('many dead images, no further re-fetch', photoFetches === before,
    `broke ${brokeMany}, ${photoFetches - before} extra fetches`);

  // This check breaks images ON PURPOSE, so it is the right place to hold
  // the policy that says a broken image is not a check failure (A102). Every
  // abort above is a "Failed to load resource" line; if those counted as
  // errors, this run — and thirteen others — would fail for the very thing
  // the product is here to recover from.
  check('the deliberate failures were recorded as noise', noise.length > 0,
    `${noise.length} lines`);
  check('and none of them counted as an error', errs.length === 0,
    JSON.stringify(errs.slice(0, 2)));

  console.log('errors:', errs.length ? errs : 'none');
  console.log(`ignored ${noise.length} resource-load line(s)`);
  await browser.close();
  if (errs.length || failed) {
    console.error(`URL REFRESH CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('URL REFRESH CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
