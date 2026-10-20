/* The payment flow on a phone — preview, checkout, order.
 *
 * Everything after the editor is a "sheet on a scrolling column": a card of
 * things to read and decide, inside a container sized to the viewport. That
 * shape has one failure mode and it is silent.
 *
 * `.sheet` sets `overflow: hidden` (it clips the gold hairline to the
 * rounded corner). A box with overflow other than visible has an automatic
 * minimum size of ZERO — so when the sheet is a flex or grid child of a
 * viewport-height container, the layout is free to squeeze it below its own
 * content, and the sheet then clips what it cannot fit. The scroll container
 * sees nothing to scroll, because as far as it knows everything fits.
 *
 * The result is a checkout form with its submit button cut off and no way to
 * scroll to it. Not "awkward on mobile" — unusable: the customer cannot buy
 * the book. `editor.css` already carries the fix for this on the START
 * screen, with a comment saying exactly what it prevents; the checkout never
 * got it.
 *
 * Why no existing check saw it: e2e drives the whole flow at 1360x850 and
 * visits a phone viewport only as far as the EDITOR. Nothing walked the
 * payment screens at a size where the squeeze happens.
 *
 * So this walks them, at a small phone size, and asks the only question that
 * matters: can a thumb reach every control? "Reachable" is measured
 * geometrically rather than by asking Playwright to click, because a click
 * can succeed on a box that a human cannot see.
 *
 *   node checks/mobileflow.js
 */
const { chromium } = require('playwright');
const path = require('path');
const { watchPage } = require('./_watch');

const BASE = 'http://127.0.0.1:8000/editor/';
/* Enough photographs to FILL the book. A 16-sheet book is 32 pages, and
   checkout refuses a book with empty ones — so a short upload here ends in
   a 409 and a bounce back to the editor, which would read as a layout
   failure and is nothing of the kind. */
const PHOTOS = Array.from({ length: 32 }, (_, i) =>
  path.join(__dirname, '..', 'fixtures', `photo${String(i % 16).padStart(2, '0')}.jpg`));

/* 375x667 is an iPhone SE / 8 — still common, and the smallest screen worth
   supporting. A bug that only shows below 390px is still a bug for the
   customer holding that phone. */
const VIEWPORT = { width: 375, height: 667 };

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

/* Can a person actually get to this control?
 *
 * The subtlety that makes this worth writing carefully: `scrollIntoView`
 * will happily scroll an `overflow: hidden` box, and a thumb will not.
 * `overflow: hidden` blocks USER scrolling, not programmatic scrolling — so
 * a naive check scrolls the clipped sheet's own hidden scroll area, finds
 * the submit button sitting in the viewport, and reports everything fine
 * while the customer stares at a form with no button on it.
 *
 * So: scroll, then put back any scrolling that happened in a box the user
 * cannot scroll, and only then measure. What is left is what a thumb can
 * reach. Then confirm the box is inside the window AND inside every
 * ancestor that clips. */
async function reachable(page, selector) {
  return page.evaluate(async (sel) => {
    const el = document.querySelector(sel);
    if (!el) return { found: false };
    const userScrollable = (node) => {
      const o = getComputedStyle(node);
      return o.overflowY === 'auto' || o.overflowY === 'scroll';
    };
    el.scrollIntoView({ block: 'center', behavior: 'instant' });
    for (let p = el.parentElement; p; p = p.parentElement) {
      if (p === document.body || p === document.documentElement) continue;
      if (!userScrollable(p)) { p.scrollTop = 0; p.scrollLeft = 0; }
    }
    await new Promise((r) => requestAnimationFrame(r));
    const box = el.getBoundingClientRect();
    const inWindow = box.top >= 0 && box.bottom <= window.innerHeight
                     && box.left >= 0 && box.right <= window.innerWidth;
    let clippedBy = null;
    for (let p = el.parentElement; p; p = p.parentElement) {
      const o = getComputedStyle(p);
      if (o.overflow === 'visible' && o.overflowY === 'visible') continue;
      const pb = p.getBoundingClientRect();
      if (box.bottom > pb.bottom + 1 || box.top < pb.top - 1) {
        clippedBy = `${p.tagName.toLowerCase()}#${p.id || p.className.split(/\s+/)[0]}`;
        break;
      }
    }
    return {
      found: true, inWindow, clippedBy,
      top: Math.round(box.top), bottom: Math.round(box.bottom),
      winH: window.innerHeight,
    };
  }, selector);
}

async function assertReachable(page, label, selector) {
  const r = await reachable(page, selector);
  if (!r.found) return check(`${label} exists`, false, selector);
  const ok = r.inWindow && !r.clippedBy;
  check(label, ok, ok ? '' :
    (r.clippedBy ? `clipped by ${r.clippedBy}`
                 : `box ${r.top}..${r.bottom} outside a ${r.winH}px window`));
  return ok;
}

/* How much of a scrolling pane's content it refuses to reveal. A sheet
   squeezed below its content reports zero scrollable height while hiding
   hundreds of pixels, so the two numbers have to be compared. */
async function hiddenInside(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    return { drawn: Math.round(el.getBoundingClientRect().height),
             needs: el.scrollHeight };
  }, selector);
}

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({
    viewport: VIEWPORT, isMobile: true, hasTouch: true, deviceScaleFactor: 2,
  })).newPage();
  const errors = [];
  const noise = watchPage(page, errors);

  console.log(`A BOOK, BUILT ON A ${VIEWPORT.width}x${VIEWPORT.height} SCREEN`);
  await page.goto(BASE);
  await page.waitForSelector('.btype:not([disabled])', { timeout: 20000 });
  await page.click('.btype[data-btype="memory"]');
  await page.waitForSelector('.tier:not([disabled])', { timeout: 15000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active', { timeout: 20000 });
  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('32 '),
    undefined, { timeout: 90000 });
  await page.click('#btn-autofill');
  await page.waitForTimeout(1200);
  check('the editor got as far as a placed book', true);

  console.log('\nPREVIEW');
  await page.click('#btn-preview');
  await page.waitForSelector('#screen-preview.active', { timeout: 20000 });
  await page.waitForFunction(
    () => document.querySelectorAll('#pv-grid .pv-page').length > 0,
    undefined, { timeout: 90000 });
  await assertReachable(page, 'the confirm checkbox', '#pv-confirm');
  await assertReachable(page, 'the price', '#pv-price');
  await assertReachable(page, 'the button out of here', '#pv-checkout');
  const pvPages = await page.$$eval('#pv-grid .pv-page', (e) => e.length);
  const lastPage = await reachable(page, '#pv-grid .pv-page:last-child');
  check(`all ${pvPages} spreads can be scrolled through`,
    lastPage.found && !lastPage.clippedBy,
    lastPage.clippedBy ? `last one clipped by ${lastPage.clippedBy}` : '');

  console.log('\nCHECKOUT — the screen that takes the money');
  await page.check('#pv-confirm');
  await page.click('#pv-checkout');
  await page.waitForSelector('#screen-checkout.active', { timeout: 20000 });

  const plain = await hiddenInside(page, '#co-form');
  check('the form is drawn at its full height',
    plain.needs - plain.drawn <= 1,
    `drawn ${plain.drawn}px, needs ${plain.needs}px — ` +
    `${Math.max(0, plain.needs - plain.drawn)}px hidden`);
  await assertReachable(page, 'the price being charged', '#co-sum-price');
  for (const [label, sel] of [['name', '[name=name]'], ['phone', '[name=phone]'],
                              ['address', '[name=address]'],
                              ['email', '[name=email]']]) {
    await assertReachable(page, `the ${label} field`, `#co-form ${sel}`);
  }
  await assertReachable(page, 'the gift toggle', '#co-gift');
  /* The one that decides whether a phone can buy a book at all. */
  await assertReachable(page, 'THE SUBMIT BUTTON',
                        '#co-form button[type=submit]');

  console.log('\nCHECKOUT WITH GIFT MODE ON — the tallest this form gets');
  await page.check('#co-gift');
  await page.waitForTimeout(400);
  const gift = await hiddenInside(page, '#co-form');
  check('the form grew instead of clipping',
    gift.needs - gift.drawn <= 1,
    `drawn ${gift.drawn}px, needs ${gift.needs}px — ` +
    `${Math.max(0, gift.needs - gift.drawn)}px hidden`);
  await assertReachable(page, "the recipient's address",
                        '#co-form [name=recipient_address]');
  await assertReachable(page, 'the deliver-after date',
                        '#co-form [name=deliver_after]');
  await assertReachable(page, 'THE SUBMIT BUTTON, still',
                        '#co-form button[type=submit]');
  await page.uncheck('#co-gift');

  console.log('\nORDER — what they see after paying');
  await page.fill('#co-form [name=name]', 'Dilnoza R.');
  await page.fill('#co-form [name=phone]', '+998 90 123 45 67');
  await page.fill('#co-form [name=address]', 'Tashkent, Chilonzor 12, kv 4');
  await page.click('#co-form button[type=submit]');
  const reached = await page.waitForSelector('#screen-order.active', { timeout: 30000 })
    .then(() => true).catch(() => false);
  check('the order screen was actually reached', reached,
    reached ? '' : await page.evaluate(() => {
      const t = document.querySelector('.toast');
      return t ? `last toast: ${t.textContent}` : 'no toast, no order screen';
    }));
  if (!reached) {
    console.log('\n(stopping here — nothing further can be measured)');
    console.log('\nerrors:', errors.length ? errors : 'none');
    await browser.close();
    console.error(`MOBILE FLOW CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  await page.waitForTimeout(1500);
  await assertReachable(page, 'the order reference', '#or-ref');
  const orBody = await hiddenInside(page, '.or-body');
  check('nothing on the order screen is clipped away',
    orBody.needs >= orBody.drawn,
    `drawn ${orBody.drawn}px, content ${orBody.needs}px`);
  const last = await page.evaluate(() => {
    const vis = [...document.querySelectorAll('.or-body > *')]
      .filter((n) => n.getBoundingClientRect().height > 0);
    const el = vis[vis.length - 1];
    el.scrollIntoView({ block: 'end', behavior: 'instant' });
    const b = el.getBoundingClientRect();
    return { id: el.id || el.className.split(/\s+/)[0],
             bottom: Math.round(b.bottom), winH: window.innerHeight };
  });
  check('the last thing on it can be scrolled to',
    last.bottom <= last.winH + 1,
    `${last.id} ends at ${last.bottom} in a ${last.winH}px window`);

  console.log('\nerrors:', errors.length ? errors : 'none');
  if (noise.length) {
    console.log(`ignored ${noise.length} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`MOBILE FLOW CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('MOBILE FLOW CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
