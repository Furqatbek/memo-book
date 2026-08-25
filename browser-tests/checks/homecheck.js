const path = require('path');
const SHOTS = path.join(__dirname, '..', 'shots');
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 1360, height: 850 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto('http://127.0.0.1:8000/editor/');
  await page.waitForSelector('.home-link');
  console.log('start-screen home label:', await page.textContent('#screen-start .home-link'));
  await page.screenshot({ path: SHOTS + '/40-home-btn-start.png' });
  // Russian label check
  await page.selectOption('#lang-select', 'ru');
  console.log('ru label:', await page.textContent('#screen-start .home-link'));
  // click navigates to site root
  await page.click('#screen-start .btn.home-link');
  await page.waitForTimeout(400);
  console.log('after click URL:', page.url());
  // editor bar icon exists too
  await page.goto('http://127.0.0.1:8000/editor/');
  await page.click('.btype[data-btype=\"memory\"]');
  await page.click('.tier[data-tier="16"]');
  // A71 put a cover-design gallery between size and editor.
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');
  const title = await page.getAttribute('#screen-editor .icon-btn.home-link', 'title');
  console.log('editor-bar icon title:', title);
  await page.screenshot({ path: SHOTS + '/41-home-btn-editor.png' });
  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) throw new Error('page errors');
  console.log('HOME LINK CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
