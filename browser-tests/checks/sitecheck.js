const path = require('path');
const SHOTS = path.join(__dirname, '..', 'shots');
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 1360, height: 900 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));

  await page.goto('http://127.0.0.1:8090/');
  await page.$eval('#stories', (el) => el.scrollIntoView());
  await page.waitForTimeout(300);
  await page.screenshot({ path: SHOTS + '/30-stories.png' });
  await page.$eval('.site-footer', (el) => el.scrollIntoView());
  await page.waitForTimeout(300);
  await page.screenshot({ path: SHOTS + '/31-footer-en.png' });

  await page.goto('http://127.0.0.1:8090/uz/');
  await page.$eval('.site-footer', (el) => el.scrollIntoView());
  await page.waitForTimeout(300);
  await page.screenshot({ path: SHOTS + '/32-footer-uz.png' });

  // mobile
  const mob = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await mob.goto('http://127.0.0.1:8090/ru/');
  await mob.$eval('#stories', (el) => el.scrollIntoView());
  await mob.waitForTimeout(300);
  await mob.screenshot({ path: SHOTS + '/33-mobile-stories-ru.png' });

  // editor brand link
  await page.goto('http://127.0.0.1:8000/editor/');
  const href = await page.$eval('#screen-start .brand', (el) => el.getAttribute('href'));
  console.log('editor brand href:', href);
  await page.$eval('#screen-start .brand', (el) => el.click());
  await page.waitForTimeout(500);
  console.log('after brand click, URL:', page.url());
  console.log('page errors:', errors.length ? errors : 'none');
  await browser.close();
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
