/* Screenshot the first screen in every language.
 * Not a check — a way to see that the display face actually draws Ҳ/ҳ and ǵ
 * rather than falling back to the system serif for one letter of a word.
 *   node checks/langshots.js
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const BASE = 'http://127.0.0.1:8000';
const OUT = path.join(__dirname, '..', 'shots', 'lang');

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1100, height: 820 } })).newPage();

  for (const lang of ['en', 'ru', 'uz', 'uz-cyrl', 'kaa']) {
    await page.goto(`${BASE}/editor/`);
    await page.evaluate((l) => { localStorage.clear(); localStorage.setItem('sb-lang', l); }, lang);
    await page.goto(`${BASE}/editor/`);
    await page.waitForFunction(
      () => document.querySelector('#screen-start h1').textContent.length > 0,
      undefined, { timeout: 30000 });
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${OUT}/${lang}.png` });
  }

  await browser.close();
  console.log('shots in', OUT);
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
