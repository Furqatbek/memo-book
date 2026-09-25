/* Change 2: "Remind me in Telegram", from the editor to the bot and back.
 *
 * Email was never a working recovery channel here — nothing in the editor
 * ever asked for an address, so the reminder job's email branch could not
 * fire for a real customer. This is the first one that does, which makes
 * the button being VISIBLE and the link being VALID the whole feature.
 *
 * The assertions that matter:
 *
 *   - the button is in the bar, not behind a panel: the person it is for
 *     is the one about to close the tab;
 *   - the deep link is NOT the edit token. It travels through Telegram,
 *     sits in a chat list and gets forwarded, and the edit token is all
 *     that stands between a stranger and these photographs;
 *   - once the bot has been started, the editor stops offering and says so;
 *   - /stop puts it back, because a customer who changed their mind has to
 *     be able to change it again.
 *
 *   node checks/tgremind.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');
const path = require('path');

const BASE = 'http://127.0.0.1:8000';
const HOOK = `${BASE}/api/v1/telegram/webhook`;
const SECRET = 'dev-telegram-secret';
const CHAT = 880011;

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

const update = (page, body) => page.request.post(HOOK, {
  headers: { 'X-Telegram-Bot-Api-Secret-Token': SECRET },
  data: body,
});

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({
    viewport: { width: 390, height: 844 },   // it has to fit the phone bar
  })).newPage();
  const errors = [];
  const noise = watchPage(page, errors);

  console.log('A BOOK, AND THE OFFER');
  await page.goto(`${BASE}/editor/`);
  await page.waitForSelector('.btype:not([disabled])', { timeout: 15000 });
  await page.click('.btype[data-btype="memory"]');
  await page.waitForSelector('.tier:not([disabled])', { timeout: 10000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active', { timeout: 15000 });
  await page.waitForSelector('#btn-tg-remind:not(.hidden)', { timeout: 15000 });

  const offer = await page.evaluate(() => {
    const a = document.getElementById('btn-tg-remind');
    const r = a.getBoundingClientRect();
    return {
      href: a.getAttribute('href') || '',
      label: a.textContent.trim(),
      visible: r.width > 0 && r.height > 0,
      inViewport: r.right <= window.innerWidth + 1,
    };
  });
  check('  the button is visible in the editor bar', offer.visible, offer.label);
  check('  it fits the phone without pushing the bar sideways', offer.inViewport);
  check('  it is a t.me deep link', /^https:\/\/t\.me\/[^?]+\?start=.+/.test(offer.href),
    offer.href);
  check('  and it is labelled, not an empty key',
    offer.label.length > 3 && !offer.label.startsWith('tg.'), offer.label);

  const token = offer.href.split('start=')[1];
  const creds = await page.evaluate(() => JSON.parse(localStorage.getItem('mb-book')));
  check('  the deep-link token is NOT the edit token',
    token && creds && token !== creds.edit_token, `${token.slice(0, 8)}…`);

  console.log('\nTHE CUSTOMER PRESSES START');
  const started = await update(page, {
    update_id: Date.now(),
    message: { message_id: 1, from: { id: 77 }, chat: { id: CHAT },
               text: `/start ${token}` },
  });
  check('  the webhook accepts it', started.status() === 200, String(started.status()));
  check('  and reports the book linked',
    (await started.json()).result === 'linked', JSON.stringify(await started.json()));

  console.log('\nTHE EDITOR STOPS OFFERING WHEN THEY COME BACK');
  // The real journey: they left for Telegram and returned to this tab.
  // Nothing reloads, so the editor has to notice by itself.
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  await page.waitForSelector('#tg-linked:not(.hidden)', { timeout: 10000 })
    .catch(() => {});
  const ui = await page.evaluate(() => ({
    offering: !document.getElementById('btn-tg-remind').classList.contains('hidden'),
    confirmed: !document.getElementById('tg-linked').classList.contains('hidden'),
    text: document.getElementById('tg-linked').textContent.trim(),
  }));
  check('  the button stops offering what they just did', !ui.offering);
  check('  and a confirmation takes its place', ui.confirmed, ui.text);

  console.log('\nAND /stop PUTS IT BACK');
  const stopped = await update(page, {
    update_id: Date.now() + 1,
    message: { message_id: 2, from: { id: 77 }, chat: { id: CHAT }, text: '/stop' },
  });
  const body = await stopped.json();
  check('  the chat is cleared', body.books_cleared >= 1, JSON.stringify(body));
  const after = await page.evaluate(async () => {
    const c = JSON.parse(localStorage.getItem('mb-book'));
    const r = await fetch(`/api/v1/books/${c.book_id}/telegram-link`,
                          { headers: { 'X-Edit-Token': c.edit_token } });
    return r.json();
  });
  check('  and the offer is available again', after.linked === false,
    JSON.stringify(after));

  console.log('\nA WRONG SECRET IS NOT AN ORACLE');
  const bad = await page.request.post(HOOK, {
    headers: { 'X-Telegram-Bot-Api-Secret-Token': 'wrong' }, data: {},
  });
  // 404 rather than 401, deliberately: a wrong secret learns nothing a
  // right one would, so this is never a way to discover that an RS Pixel
  // bot lives at this host (A96).
  check('  it answers 404, revealing nothing', bad.status() === 404,
    String(bad.status()));

  console.log('\nerrors:', errors.length ? errors : 'none');
  if (noise.length) {
    console.log(`ignored ${noise.length} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`TELEGRAM REMINDER CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('TELEGRAM REMINDER CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
