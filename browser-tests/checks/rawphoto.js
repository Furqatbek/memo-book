/* A103: a RAW photo goes into a book, and a refusal says why.
 *
 * Two bugs met here, and both of them were silent.
 *
 * The editor refused a .dng before it ever left the browser — the file
 * picker did not offer one, and a dragged-in file produced a red card
 * reading "Failed" and nothing else. Nothing said the format was the
 * problem, so the only way to find out was to ask.
 *
 * And had one reached the server, it would have been ACCEPTED. A DNG is a
 * TIFF container whose first image is a thumbnail, so ingest read 320x240,
 * raised nothing, and would have put a 12-megapixel photograph into a
 * printed book as a postage stamp.
 *
 * The fixture is a DNG built by `backend/tests/dng_fixture.py`: a 320x240
 * thumbnail in IFD0 and the real 2400x1800 picture in a SubIFD, which is
 * exactly the layout that made this invisible. If this check ever reports
 * 320x240, the SubIFD is being ignored again. To rebuild it:
 *
 *   cd backend && .venv/bin/python -c "from tests.dng_fixture import build_dng; \
 *     open('../browser-tests/fixtures/prorawA.dng','wb').write(build_dng( \
 *       thumb_size=(320,240), preview_size=(2400,1800), \
 *       taken_at='2024:07:14 09:30:00'))"
 *
 *   node checks/rawphoto.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');
const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:8000';
const SHOTS = path.join(__dirname, '..', 'shots');
const FIXTURES = path.join(__dirname, '..', 'fixtures');
const RAW = path.join(FIXTURES, 'prorawA.dng');
// Something we genuinely do not take, to prove the refusal names itself.
const UNSUPPORTED = path.join(SHOTS, 'not-a-photo.bmp');

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

const cardText = (page, selector) =>
  page.$eval(selector, (el) => el.textContent.trim()).catch(() => '');

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  // A real BMP header, so the only thing wrong with it is that it is a BMP.
  const bmp = Buffer.alloc(70);
  bmp.write('BM', 0);
  bmp.writeUInt32LE(70, 2);
  bmp.writeUInt32LE(54, 10);
  bmp.writeUInt32LE(40, 14);
  fs.writeFileSync(UNSUPPORTED, bmp);

  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1360, height: 900 } })).newPage();
  const errors = [];
  const noise = watchPage(page, errors);

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

  console.log('THE FILE PICKER OFFERS RAW AT ALL');
  const accept = await page.$eval('#file-input', (el) => el.getAttribute('accept'));
  check('the picker lists .dng', /\.dng/i.test(accept), accept.slice(0, 60));

  console.log('A RAW PHOTO UPLOADS AND INGESTS');
  await page.setInputFiles('#file-input', [RAW]);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('1 '),
    undefined, { timeout: 180000 });
  check('the .dng became a usable photo',
    (await page.$$('#tray-grid .ph-card.job.failed')).length === 0);

  // The load-bearing assertion. The card's tooltip is the ingested size, so
  // this is the SubIFD picture, not the thumbnail beside it.
  const title = await page.$eval('#tray-grid .ph-card', (el) => el.title || '');
  check('and it came in at full size, not as the thumbnail',
    title.startsWith('2400×1800'), JSON.stringify(title));
  check('so it is not badged as too small to print',
    (await page.$$('#tray-grid .ph-card .badge.warn')).length === 0);
  await page.screenshot({ path: `${SHOTS}/103-raw-ingested.png` });

  console.log('AND IT CAN BE PLACED LIKE ANY OTHER PHOTO');
  await page.click('#btn-autofill');
  // Waiting for the BADGE, not for the save that precedes it. A saved
  // layout and a redrawn tray are two different moments, and asserting on
  // the first while meaning the second is how a check becomes a flake
  // (A101, A102).
  const placed = await page.waitForSelector('#tray-grid .badge.ok', { timeout: 60000 })
    .then(() => true).catch(() => false);
  check('autofill placed it', placed);

  console.log('A REFUSAL SAYS WHY, NOT JUST THAT');
  await page.setInputFiles('#file-input', [UNSUPPORTED]);
  await page.waitForSelector('#tray-grid .ph-card.job.failed', { timeout: 15000 });
  const why = await cardText(page, '#tray-grid .ph-card.job.failed .ph-why');
  check('the red card carries a reason', why.length > 0, JSON.stringify(why));
  // The specific failure this check exists for: "Failed" alone is what sent
  // somebody to ask whether the site was broken.
  check('and the reason is about the FILE TYPE',
    /file|type|read/i.test(why), JSON.stringify(why));
  await page.screenshot({ path: `${SHOTS}/103-refusal-names-itself.png` });

  console.log('IN A LANGUAGE THE CUSTOMER READS');
  // Set before load rather than through the picker: the language control
  // lives on the start screen and is not on screen inside the editor, so
  // driving it from here would be testing an element nobody can reach.
  // A refused job only exists in the page that refused it, so the upload is
  // repeated after the reload rather than expected to survive it.
  await page.evaluate(() => localStorage.setItem('sb-lang', 'ru'));
  await page.reload();
  // A reload lands on the start screen offering to continue the saved book.
  await page.waitForSelector('#btn-resume', { timeout: 30000 });
  await page.click('#btn-resume');
  await page.waitForSelector('#screen-editor.active', { timeout: 30000 });
  await page.setInputFiles('#file-input', [UNSUPPORTED]);
  await page.waitForSelector('#tray-grid .ph-card.job.failed .ph-why', { timeout: 15000 });
  const ruWhy = await cardText(page, '#tray-grid .ph-card.job.failed .ph-why');
  check('the reason is translated, not left in English',
    ruWhy.length > 0 && ruWhy !== why, JSON.stringify(ruWhy));
  check('and it is not a raw i18n key',
    !/^upload\.|^photoerr\./.test(ruWhy), JSON.stringify(ruWhy));

  console.log('errors:', errors.length ? errors : 'none');
  if (noise.length) {
    console.log(`ignored ${noise.length} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`RAW PHOTO CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('RAW PHOTO CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
