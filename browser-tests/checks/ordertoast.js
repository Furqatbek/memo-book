/* P1-5: the editor says what auto-fill did, and only what it did.
 *
 * The ordering is the best thing this button does, and for five languages
 * the toast reported two numbers, so the customer never learned it
 * happened. But it only happens when the photos carry dates. EXIF is
 * stripped by Telegram and WhatsApp and screenshots never had any, so a
 * book assembled from forwarded photos is placed in UPLOAD order — and
 * "in the order you took them" would be a lie told at the one moment the
 * customer could still fix the order by hand.
 *
 * So there are three sentences, and this check is here to prove the right
 * one appears. The expected phrases are written out below rather than read
 * back from i18n.js: a check that derives its expectation from the thing
 * it is checking passes just as happily when the copy is wrong.
 *
 * The undated fixtures are the real ones with their APP1/EXIF segment cut
 * out, which is exactly what a messenger does to them.
 *
 *   node checks/ordertoast.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:8000';
const SHOTS = path.join(__dirname, '..', 'shots');
const FIXTURES = path.join(__dirname, '..', 'fixtures');

const dated = (n) => path.join(FIXTURES, `photo0${n}.jpg`);

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

/* Cut every APP1 segment out of a JPEG — what a messenger does on the way
   through, and the reason the undated case is the common one. */
function stripExif(buf) {
  if (buf.readUInt16BE(0) !== 0xffd8) throw new Error('not a JPEG');
  const out = [buf.subarray(0, 2)];
  let i = 2;
  while (i < buf.length - 1) {
    const marker = buf.readUInt16BE(i);
    if (marker === 0xffda) { out.push(buf.subarray(i)); break; }  // image data
    const len = buf.readUInt16BE(i + 2);
    if (marker !== 0xffe1) out.push(buf.subarray(i, i + 2 + len));
    i += 2 + len;
  }
  return Buffer.concat(out);
}

function undated(n) {
  const dest = path.join(SHOTS, `nodate0${n}.jpg`);
  fs.writeFileSync(dest, stripExif(fs.readFileSync(dated(n))));
  return dest;
}

async function newBook(page, lang) {
  await page.goto(`${BASE}/editor/`);
  if (lang) {
    // The start screen is the only place the language can be chosen — once
    // the editor is open the selector is gone — so a language is picked
    // here and the whole book is made in it, which is what a customer does.
    await page.evaluate((l) => localStorage.setItem('sb-lang', l), lang);
    await page.goto(`${BASE}/editor/`);
  }
  await page.waitForSelector('.btype:not([disabled])', { timeout: 15000 });
  await page.click('.btype[data-btype="memory"]');
  await page.waitForSelector('.tier:not([disabled])', { timeout: 10000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active', { timeout: 15000 });
}

async function upload(page, files) {
  await page.setInputFiles('#file-input', files);
  await page.waitForFunction(
    (n) => document.getElementById('tray-count').textContent.startsWith(`${n} `),
    files.length, { timeout: 120000 });
}

/* Click auto-fill and return everything it said. Toasts self-remove after
   4.5s, so they are read as they arrive rather than after the layout
   settles. */
async function autoFillToast(page) {
  await page.evaluate(() => {
    window.__toasts = [];
    const box = document.getElementById('toasts');
    new MutationObserver((muts) => {
      for (const m of muts) {
        for (const node of m.addedNodes) window.__toasts.push(node.textContent.trim());
      }
    }).observe(box, { childList: true });
  });
  await page.click('#btn-autofill');
  await page.waitForFunction(() => window.__toasts.length > 0, undefined, { timeout: 30000 });
  return page.evaluate(() => window.__toasts.join(' | '));
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1360, height: 900 } })).newPage();
  const errors = [];
  const noise = watchPage(page, errors);

  console.log('EVERY PHOTO CARRIES A DATE — it may claim the order');
  await newBook(page);
  await upload(page, [dated(0), dated(1), dated(2)]);
  let said = await autoFillToast(page);
  console.log(`   toast: ${said}`);
  check('it says the photos are in the order they were taken',
    /in the order you took them/i.test(said), said);
  check('and does not report a count that did not fit',
    !/did not fit/i.test(said), said);
  await page.screenshot({ path: path.join(SHOTS, 'ordertoast-dated.png') });

  console.log('\nNO PHOTO CARRIES A DATE — it must not claim the order');
  await newBook(page);
  await upload(page, [undated(0), undated(1), undated(2)]);
  said = await autoFillToast(page);
  console.log(`   toast: ${said}`);
  // The assertion that matters. This is the forwarded-from-Telegram book,
  // and the one case where the marketing claim is not true of it.
  check('it does NOT claim the order they were taken',
    !/in the order you took them/i.test(said), said);
  check('it says they are in the order they were added',
    /in the order you added them/i.test(said), said);
  check('and says why — the photos carry no date',
    /no date/i.test(said), said);
  await page.screenshot({ path: path.join(SHOTS, 'ordertoast-undated.png') });

  console.log('\nSOME OF EACH — it reports how many it could date');
  await newBook(page);
  await upload(page, [dated(3), dated(4), undated(5), undated(6)]);
  said = await autoFillToast(page);
  console.log(`   toast: ${said}`);
  check('it does NOT claim the whole book is in that order',
    !/in the order you took them/i.test(said), said);
  check('it names how many carried a date', /\b2\b/.test(said), said);
  check('and says the undated ones come after',
    /after/i.test(said), said);

  console.log('\nIN RUSSIAN — the honest sentence is the one that got translated');
  // The undated case again, because it is the one that must not overclaim,
  // and a translation that quietly falls back to the English string would
  // be the easiest thing in this change to miss.
  await newBook(page, 'ru');
  await upload(page, [undated(7), undated(8)]);
  said = await autoFillToast(page);
  console.log(`   toast: ${said}`);
  check('the toast is in Russian', /[А-Яа-я]/.test(said), said);
  check('it is not the untranslated key', !/autofill\./.test(said), said);
  check('it has not fallen back to English',
    !/placed|in the order/i.test(said), said);
  check('it does NOT claim the order they were taken — снимали',
    !/снимали/i.test(said), said);
  check('it says they are in the order they were added — добавили',
    /добавили/i.test(said), said);
  await page.screenshot({ path: path.join(SHOTS, 'ordertoast-ru.png') });

  console.log('\nerrors:', errors.length ? errors : 'none');
  if (noise.length) {
    console.log(`ignored ${noise.length} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`ORDER TOAST CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('ORDER TOAST CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
