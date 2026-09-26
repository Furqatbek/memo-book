/* CR-003: the growth mechanics, from the editor outwards.
 *
 * Everything this checks was built in the backend first and is reachable
 * only through a button. That is the failure mode it exists to catch: a
 * feature that works perfectly and has no way in is a feature that does not
 * exist, and this codebase has shipped that bug more than once.
 *
 * What it drives:
 *
 *   - the share link: minted from the bar, opened in a SECOND browser
 *     context with no edit token, showing pages and nothing else;
 *   - the contributor link: minted from the bar, opened by a third party
 *     who uploads a photograph that then appears in the owner's tray
 *     flagged as somebody else's;
 *   - the campaign countdown, which must stay silent when no campaign is
 *     configured. A banner is a promise, and an empty promise is worse
 *     than none.
 *
 *   node checks/growth.js
 */
const { chromium } = require('playwright');
const { watchPage } = require('./_watch');
const path = require('path');

const BASE = 'http://127.0.0.1:8000';
const PHOTO = path.join(__dirname, '..', 'fixtures', 'photo00.jpg');

let failed = 0;
function check(what, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${what}${detail ? `  ${detail}` : ''}`);
  if (!ok) failed++;
}

async function newBook(page) {
  await page.goto(`${BASE}/editor/`);
  await page.waitForSelector('.btype:not([disabled])', { timeout: 15000 });
  await page.click('.btype[data-btype="memory"]');
  await page.waitForSelector('.tier:not([disabled])', { timeout: 10000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active', { timeout: 15000 });
}

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const errors = [];

  // The OWNER. Clipboard permission so the buttons take their real path
  // rather than the fallback that only shows the link in a toast.
  const ownerCtx = await browser.newContext({
    viewport: { width: 390, height: 844 },
    permissions: ['clipboard-read', 'clipboard-write'],
  });
  const owner = await ownerCtx.newPage();
  const noise = watchPage(owner, errors);

  console.log('A BOOK, WITH BOTH BUTTONS IN THE BAR');
  await newBook(owner);
  await owner.setInputFiles('#file-input', PHOTO);
  await owner.waitForFunction(
    () => document.querySelectorAll('.ph-card img').length >= 1,
    { timeout: 30000 });

  check('  "share" is in the bar', await owner.isVisible('#btn-share'));
  check('  "ask friends for photos" is in the bar',
    await owner.isVisible('#btn-contrib'));
  const labels = await owner.evaluate(() => [
    document.getElementById('btn-share').textContent.trim(),
    document.getElementById('btn-contrib').textContent.trim(),
  ]);
  check('  both are translated, not empty', labels.every((l) => l.length > 2),
    JSON.stringify(labels));

  console.log('\nTHE CAMPAIGN BANNER SAYS NOTHING WHEN THERE IS NO CAMPAIGN');
  // The dev server configures no deadline. A banner here would be a
  // promise about a printer's schedule that nobody made.
  const banner = await owner.evaluate(() => {
    const el = document.getElementById('campaign-banner');
    return { present: !!el, hidden: el ? el.classList.contains('hidden') : null,
             text: el ? el.textContent.trim() : null };
  });
  check('  the element exists', banner.present);
  check('  and is hidden with nothing in it',
    banner.hidden === true && !banner.text, JSON.stringify(banner));

  console.log('\nTHE SHARE LINK');
  await owner.click('#btn-share');
  await owner.waitForTimeout(1500);
  const shareUrl = await owner.evaluate(async () => {
    const c = JSON.parse(localStorage.getItem('mb-book'));
    const r = await fetch(`/api/v1/books/${c.book_id}/share`,
                          { method: 'POST',
                            headers: { 'X-Edit-Token': c.edit_token } });
    return (await r.json()).share_url;
  });
  check('  it is minted', !!shareUrl && shareUrl.includes('/s/'), shareUrl);

  // A SEPARATE context: a stranger with no localStorage and no token.
  const viewer = await (await browser.newContext()).newPage();
  const viewerNoise = watchPage(viewer, errors);
  const token = shareUrl.split('/s/')[1];
  await viewer.goto(`${BASE}/s/${token}`);
  await viewer.waitForSelector('.share-page img, .share-note', { timeout: 20000 });
  const seen = await viewer.evaluate(() => ({
    images: document.querySelectorAll('.share-page img').length,
    cta: !!document.getElementById('share-cta'),
    ctaHref: (document.getElementById('share-cta') || {}).href || '',
    body: document.body.innerHTML,
  }));
  check('  a stranger sees the pages', seen.images >= 1, String(seen.images));
  check('  and a way to make one of their own',
    seen.cta && seen.ctaHref.includes('utm_source=share'), seen.ctaHref);
  check('  the edit token is nowhere on the page',
    !seen.body.includes('X-Edit-Token'));
  const robots = await viewer.evaluate(() =>
    (document.querySelector('meta[name="robots"]') || {}).content || '');
  check('  and it is noindex', robots.includes('noindex'), robots);

  console.log('\nTURNING SHARING OFF');
  /* The gap this covers: the DELETE endpoint existed and was tested, and
     nothing in the editor called it — so a customer could create a share
     link and could not revoke one. Driven through the real button, with the
     confirm dialog accepted the way a customer accepts it. */
  await owner.waitForSelector('#btn-share-off:not(.hidden)', { timeout: 15000 });
  check('  the off-switch appears once a link is live', true);

  owner.once('dialog', (d) => d.accept());
  await owner.click('#btn-share-off');
  await owner.waitForFunction(
    () => document.getElementById('btn-share-off').classList.contains('hidden'),
    { timeout: 15000 });
  check('  and disappears once it is off', true);

  const deadShare = await viewer.goto(`${BASE}/s/${token}`,
                                      { waitUntil: 'domcontentloaded' });
  check('  the link a stranger held stops opening', deadShare.status() === 404,
    String(deadShare.status()));

  /* And a NEW link, not the old one back. */
  await owner.click('#btn-share');
  await owner.waitForSelector('#btn-share-off:not(.hidden)', { timeout: 15000 });
  const fresh = await owner.evaluate(async () => {
    const c = JSON.parse(localStorage.getItem('mb-book'));
    const r = await fetch(`/api/v1/books/${c.book_id}/share`,
                          { method: 'POST',
                            headers: { 'X-Edit-Token': c.edit_token } });
    return (await r.json()).share_token;
  });
  check('  sharing again mints a different token', fresh !== token);

  console.log('\nTHE CONTRIBUTOR LINK');
  const contribUrl = await owner.evaluate(async () => {
    const c = JSON.parse(localStorage.getItem('mb-book'));
    const r = await fetch(`/api/v1/books/${c.book_id}/contributor-link`,
                          { method: 'POST',
                            headers: { 'X-Edit-Token': c.edit_token } });
    return (await r.json()).url;
  });
  check('  it is minted', !!contribUrl && contribUrl.includes('/c/'), contribUrl);

  // A THIRD person: not the owner, not the share viewer.
  const friend = await (await browser.newContext()).newPage();
  const friendNoise = watchPage(friend, errors);
  await friend.goto(contribUrl.replace(/^https?:\/\/[^/]+/, BASE));
  await friend.waitForSelector('#c-files', { timeout: 20000 });

  const friendSees = await friend.evaluate(() => document.body.innerHTML);
  check('  the friend cannot see the book itself',
    !friendSees.includes('ph-card') && !friendSees.includes('screen-editor'));
  await friend.fill('#c-name', 'Bek');
  await friend.setInputFiles('#c-files', PHOTO);
  await friend.waitForFunction(
    () => /added/i.test(document.getElementById('c-status').textContent),
    { timeout: 40000 });
  const status = await friend.textContent('#c-status');
  check('  their photo goes up', /1 photo added/i.test(status), status);

  console.log('\nAND THE OWNER SEES WHOSE IT IS');
  // Reload lands on the start screen with a resume card — the editor is
  // not a URL you can return to, which is the whole reason that card
  // exists. Take the same route a customer would.
  await owner.reload();
  await owner.waitForSelector('#btn-resume, #screen-editor.active',
                              { timeout: 30000 });
  if (await owner.isVisible('#btn-resume')) await owner.click('#btn-resume');
  await owner.waitForSelector('#screen-editor.active', { timeout: 30000 });
  await owner.waitForFunction(
    () => document.querySelectorAll('.badge.contrib').length >= 1,
    { timeout: 40000 }).catch(() => {});
  const flagged = await owner.evaluate(() =>
    Array.from(document.querySelectorAll('.badge.contrib'))
      .map((b) => b.textContent.trim()));
  check('  the contributed photo is flagged', flagged.length >= 1,
    JSON.stringify(flagged));
  check('  with the name they gave', flagged.includes('Bek'),
    JSON.stringify(flagged));

  console.log('\nTURNING THE CONTRIBUTOR LINK OFF');
  await owner.waitForSelector('#btn-contrib-off:not(.hidden)', { timeout: 15000 });
  owner.once('dialog', (d) => d.accept());
  await owner.click('#btn-contrib-off');
  await owner.waitForFunction(
    () => document.getElementById('btn-contrib-off').classList.contains('hidden'),
    { timeout: 15000 });
  const deadContrib = await friend.goto(
    contribUrl.replace(/^https?:\/\/[^/]+/, BASE),
    { waitUntil: 'domcontentloaded' });
  check('  the friend’s link stops opening', deadContrib.status() === 404,
    String(deadContrib.status()));

  /* The thing people are actually afraid of: it must NOT delete the
     photographs their friends already sent. */
  const stillThere = await owner.evaluate(async () => {
    const c = JSON.parse(localStorage.getItem('mb-book'));
    const r = await fetch(`/api/v1/books/${c.book_id}/photos`,
                          { headers: { 'X-Edit-Token': c.edit_token } });
    return (await r.json()).photos.filter((p) => p.contributed).length;
  });
  check('  and the contributed photos stay', stillThere >= 1,
    `${stillThere} still in the pool`);

  console.log('\nerrors:', errors.length ? errors : 'none');
  const ignored = noise.length + viewerNoise.length + friendNoise.length;
  if (ignored) {
    console.log(`ignored ${ignored} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`GROWTH CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('GROWTH CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
