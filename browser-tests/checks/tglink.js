/* A97: linking a Telegram account from the admin console.
 *
 * The round trip, driven for real: the console issues a code, the BOT side
 * redeems it by posting to the webhook exactly as Telegram would, and the
 * console then shows — and can remove — the linked account.
 *
 * The point of the design is that these are two different surfaces. The code
 * is only ever visible to someone signed into the console; a code the bot
 * handed out would be visible to everyone in the chat, which is the surface
 * the link exists to distrust. So this check reads the code from the PAGE and
 * spends it over HTTP, rather than shortcutting through the API for both.
 *
 * Needs ADMIN_TOKEN=dev-admin and TELEGRAM_WEBHOOK_SECRET (the dev server
 * sets both by default).
 *
 *   node checks/tglink.js
 */
const { chromium } = require('playwright');
const path = require('path');
const BASE = 'http://127.0.0.1:8000';
const TOKEN = 'dev-admin';
const SECRET = 'dev-telegram-secret';
const SHOTS = path.join(__dirname, '..', 'shots');
const USER_ID = 8675309;

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

/* Exactly the request Telegram makes, secret header and all. */
async function asTheBot(text, userId = USER_ID) {
  const resp = await fetch(`${BASE}/api/v1/telegram/webhook`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json',
               'X-Telegram-Bot-Api-Secret-Token': SECRET },
    body: JSON.stringify({ message: {
      message_id: 1, chat: { id: -100999 }, text,
      from: { id: userId, username: 'checkbot', first_name: 'Check' } } }),
  });
  return resp.status;
}

(async () => {
  require('fs').mkdirSync(SHOTS, { recursive: true });

  // Start clean: a previous run may have linked this same id.
  await fetch(`${BASE}/api/v1/admin/telegram/operators/${USER_ID}`,
    { method: 'DELETE', headers: { 'X-Admin-Token': TOKEN } });

  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e)));

  console.log('THE CONSOLE ISSUES A CODE');
  await page.goto(`${BASE}/admin/`);
  await page.fill('#login-token', TOKEN);
  await page.click('#login-form button[type=submit]');
  await page.waitForSelector('#tab-orders', { timeout: 20000 });
  await page.click('.tab[data-tab="telegram"]');
  await page.waitForSelector('#tab-telegram:not(.hidden)', { timeout: 20000 });

  check('the webhook warning is hidden when it is configured',
    await page.isHidden('#tg-webhook-warn'));

  await page.click('#tg-new-code');
  await page.waitForSelector('#tg-code-box:not(.hidden)', { timeout: 20000 });
  const code = (await page.textContent('#tg-code')).trim();
  check('a code appears on screen', /^[A-Z0-9]{8}$/.test(code), code);
  await page.screenshot({ path: `${SHOTS}/97-console-code.png` });

  console.log('THE BOT REDEEMS IT');
  check('an unlinked account cannot list orders yet',
    (await asTheBot('/orders')) === 200);
  const before = await (await fetch(`${BASE}/api/v1/admin/telegram/operators`,
    { headers: { 'X-Admin-Token': TOKEN } })).json();
  check('and is not in the list',
    !(before.operators || []).some((o) => o.telegram_user_id === USER_ID));

  check('the webhook accepts /link', (await asTheBot(`/link ${code}`)) === 200);

  const after = await (await fetch(`${BASE}/api/v1/admin/telegram/operators`,
    { headers: { 'X-Admin-Token': TOKEN } })).json();
  const linked = (after.operators || []).find((o) => o.telegram_user_id === USER_ID);
  check('the account is now linked', !!linked,
    JSON.stringify(linked && linked.username));

  console.log('THE CODE IS SPENT');
  await asTheBot(`/link ${code}`, USER_ID + 1);
  const others = await (await fetch(`${BASE}/api/v1/admin/telegram/operators`,
    { headers: { 'X-Admin-Token': TOKEN } })).json();
  check('the same code cannot link a second account',
    !(others.operators || []).some((o) => o.telegram_user_id === USER_ID + 1));

  console.log('AND THE CONSOLE CAN TAKE IT AWAY');
  await page.click('.tab[data-tab="orders"]');
  await page.click('.tab[data-tab="telegram"]');
  await page.waitForFunction(
    (id) => [...document.querySelectorAll('#tg-operators .tg-op')]
      .some((el) => el.textContent.includes(String(id))),
    USER_ID, { timeout: 20000 });
  check('the linked account is shown in the console', true);
  await page.screenshot({ path: `${SHOTS}/97-console-linked.png` });

  page.on('dialog', (d) => d.accept());
  await page.click('#tg-operators .tg-op .btn.danger');
  await page.waitForFunction(
    (id) => ![...document.querySelectorAll('#tg-operators .tg-op')]
      .some((el) => el.textContent.includes(String(id))),
    USER_ID, { timeout: 20000 });

  const gone = await (await fetch(`${BASE}/api/v1/admin/telegram/operators`,
    { headers: { 'X-Admin-Token': TOKEN } })).json();
  check('Remove actually revokes it on the server',
    !(gone.operators || []).some((o) => o.telegram_user_id === USER_ID));

  console.log('errors:', errs.length ? errs : 'none');
  await browser.close();
  if (errs.length || failed) {
    console.error(`TELEGRAM LINK CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('TELEGRAM LINK CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
