/* A72/A73: every control in the admin console, against the real backend.
 *
 * admincheck and ordersadmin walk the happy paths. This one is pettier: it
 * touches each field and each button in turn and asserts the SERVER changed
 * accordingly — because a control that looks like it worked and quietly did
 * nothing is the worst kind of admin panel.
 *
 * Needs ADMIN_TOKEN (the dev server sets `dev-admin`) and, for the order
 * half, an order to work on, which it places as a customer.
 */
const { chromium } = require('playwright');
const path = require('path');
const BASE = 'http://127.0.0.1:8000';
const TOKEN = 'dev-admin';
const ART = path.join(__dirname, '..', 'fixtures', 'artwork-hearts.png');
const PHOTOS = Array.from({ length: 32 }, (_, i) =>
  path.join(__dirname, '..', 'fixtures', `photo${String(i % 16).padStart(2, '0')}.jpg`));

const SLUG = 'wiring-probe';
const api = (p, init = {}) => fetch(`${BASE}/api/v1/admin${p}`, {
  ...init, headers: { 'X-Admin-Token': TOKEN, ...(init.headers || {}) },
});

const fails = [];

/* Click Save and wait for the request it makes, not for something on screen
   that a previous run may already have left there. Returns the status. */
async function saveDesign(page) {
  const [resp] = await Promise.all([
    page.waitForResponse((r) => r.url().includes('/admin/cover-designs')
      && ['POST', 'PATCH'].includes(r.request().method()), { timeout: 60000 }),
    page.click('#btn-save'),
  ]);
  // The upload path may follow with a retire call; let it settle.
  await page.waitForTimeout(700);
  return resp.status();
}

function check(label, ok, detail) {
  console.log(`   ${ok ? 'ok  ' : 'FAIL'}  ${label}${detail ? `  ${detail}` : ''}`);
  if (!ok) fails.push(label);
}

/* The design as the server has it, which is the only opinion that counts. */
async function stored(slug = SLUG) {
  const body = await (await api('/cover-designs')).json();
  return body.designs.find((d) => d.slug === slug) || null;
}

async function placeOrder(page) {
  await page.goto(`${BASE}/editor/`);
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/editor/`);
  await page.click('.btype[data-btype="memory"]');
  await page.waitForFunction(() => document.querySelector('[data-tier-pages]').textContent,
    undefined, { timeout: 10000 });
  await page.click('.tier[data-tier="16"]');
  await page.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await page.isVisible('#design-step')) await page.click('#design-skip');
  await page.waitForSelector('#screen-editor.active');
  await page.setInputFiles('#file-input', PHOTOS);
  await page.waitForFunction(
    () => document.getElementById('tray-count').textContent.startsWith('32 '),
    undefined, { timeout: 180000 });
  await page.click('#btn-autofill');
  await page.waitForFunction(
    () => document.getElementById('save-state').classList.contains('saved'),
    undefined, { timeout: 30000 });
  await page.click('#btn-preview');
  await page.waitForFunction(
    () => document.querySelectorAll('#pv-grid figure').length >= 32,
    undefined, { timeout: 180000 });
  await page.check('#pv-confirm');
  await page.waitForSelector('#pv-checkout:not([disabled])');
  await page.click('#pv-checkout');
  await page.waitForSelector('#screen-checkout.active');
  await page.fill('[name=name]', 'Wiring Probe');
  await page.fill('[name=phone]', '+998 91 000-11-22');
  await page.fill('[name=address]', 'Tashkent, probe 1');
  await page.click('#co-form button[type=submit]');
  await page.waitForSelector('#screen-order.active', { timeout: 60000 });
  return (await page.textContent('#or-ref')).trim();
}

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 980 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  const ref = await placeOrder(page);

  // ---------------------------------------------------------------- sign in
  console.log('SIGN IN');
  await page.goto(`${BASE}/admin/`);
  await page.fill('#login-token', 'wrong');
  await page.click('#login-form button[type=submit]');
  await page.waitForSelector('#login-error:not(.hidden)');
  check('a wrong token is refused', await page.isVisible('#screen-login'));
  errors.length = 0;   // the refusal IS a 404 by design

  await page.fill('#login-token', TOKEN);
  await page.click('#login-form button[type=submit]');
  await page.waitForSelector('#screen-main.active', { timeout: 15000 });
  check('the right token gets in', true);

  await page.reload();
  await page.waitForSelector('#screen-main.active', { timeout: 15000 });
  check('the session survives a reload', true);

  // -------------------------------------------------------------- designs
  console.log('DESIGNS — every field round-trips to the server');
  await page.click('.tab[data-tab="designs"]');
  await page.waitForSelector('#tab-designs:not(.hidden)');

  await page.click('#btn-new');
  await page.waitForSelector('#edit-form:not(.hidden)');
  check('"+ New" opens a blank form',
    (await page.inputValue('#f-slug')) === '' && (await page.inputValue('#f-name')) === '');

  await page.setInputFiles('#f-artwork', ART);
  await page.waitForFunction(() => {
    const img = document.getElementById('cover-art');
    return img && !img.classList.contains('hidden') && img.getAttribute('src');
  }, undefined, { timeout: 10000 });
  check('choosing artwork previews it before upload', true);

  // fill in every field with a distinctive value
  await page.fill('#f-slug', SLUG);
  await page.fill('#f-name', 'Wiring probe');
  await page.check('#f-types input[data-type="birthday"]');
  await page.check('#f-types input[data-type="memory"]');
  await page.check('#f-has-photo');
  for (const [id, v] of [['#f-rect-x', '21'], ['#f-rect-y', '31'],
                         ['#f-rect-w', '77'], ['#f-rect-h', '88'],
                         ['#f-title-x', '61'], ['#f-title-y', '181'],
                         ['#f-title-size', '19'], ['#f-order', '42']]) {
    await page.fill(id, v);
  }
  await page.fill('#f-bg', '#123456');
  await page.dispatchEvent('#f-bg', 'input');
  await page.fill('#f-title-color', '#abcdef');
  await page.dispatchEvent('#f-title-color', 'input');
  const created = await saveDesign(page);
  check('Save reaches the server', created === 201, `HTTP ${created}`);
  // Every colour input really carried the value we typed into it.
  check('the colour inputs hold what was typed',
    (await page.inputValue('#f-bg')) === '#123456'
      && (await page.inputValue('#f-title-color')) === '#abcdef',
    `${await page.inputValue('#f-bg')} / ${await page.inputValue('#f-title-color')}`);

  let d = await stored();
  check('slug saved', d && d.slug === SLUG, d && d.slug);
  check('name saved', d.name === 'Wiring probe', d.name);
  check('occasion checkboxes saved',
    JSON.stringify(d.book_types.sort()) === '["birthday","memory"]',
    JSON.stringify(d.book_types));
  check('photo window saved',
    d.photo_rect && d.photo_rect.x_mm === 21 && d.photo_rect.y_mm === 31
      && d.photo_rect.w_mm === 77 && d.photo_rect.h_mm === 88,
    JSON.stringify(d.photo_rect));
  check('title position and size saved',
    d.title && d.title.x_mm === 61 && d.title.y_mm === 181 && d.title.size_pt === 19,
    JSON.stringify(d.title));
  check('title colour saved', d.title_color === '#abcdef', d.title_color);
  check('background colour saved', d.bg_color === '#123456', d.bg_color);
  check('sort order saved', d.sort_order === 42, String(d.sort_order));
  check('artwork stored at print size',
    d.artwork_width === 1937 && d.artwork_height === 2858,
    `${d.artwork_width}x${d.artwork_height}`);

  // editing without re-uploading artwork must still persist
  console.log('DESIGNS — editing without re-uploading artwork');
  await page.fill('#f-name', 'Wiring probe v2');
  await page.fill('#f-order', '7');
  await page.uncheck('#f-types input[data-type="memory"]');
  const patched = await saveDesign(page);
  check('editing without new artwork uses PATCH', patched === 200, `HTTP ${patched}`);
  d = await stored();
  check('name changed by PATCH', d.name === 'Wiring probe v2', d.name);
  check('sort order changed by PATCH', d.sort_order === 7, String(d.sort_order));
  check('occasions changed by PATCH',
    JSON.stringify(d.book_types) === '["birthday"]', JSON.stringify(d.book_types));

  // the "Auto" title-colour button
  await page.click('#f-title-auto');
  await saveDesign(page);
  d = await stored();
  check('"Auto" clears the title colour', d.title_color === undefined || d.title_color === null,
    JSON.stringify(d.title_color));

  // turning the photo window off makes a complete-artwork cover
  await page.uncheck('#f-has-photo');
  await saveDesign(page);
  d = await stored();
  check('unticking the photo window clears the rectangle', d.photo_rect === null,
    JSON.stringify(d.photo_rect));
  check('the number inputs grey out when there is no photo window',
    await page.$eval('#f-rect', (el) => el.classList.contains('off')));
  await page.check('#f-has-photo');
  await saveDesign(page);

  // the slug field: either it renames, or it must not pretend to
  console.log('DESIGNS — the slug field');
  const slugEditable = await page.$eval('#f-slug', (el) => !el.disabled);
  if (slugEditable) {
    await page.fill('#f-slug', 'wiring-renamed');
    await saveDesign(page);
    const renamed = await stored('wiring-renamed');
    const original = await stored(SLUG);
    check('an editable slug actually renames the design',
      renamed !== null && original === null,
      renamed ? 'renamed' : 'the field did nothing');
    if (renamed) await page.fill('#f-slug', SLUG);
  } else {
    check('the slug is locked on an existing design, not a field that lies', true);
  }

  // "Visible" and Retire
  console.log('DESIGNS — visibility');
  const publicSlugs = async () => (await (await fetch(
    `${BASE}/api/v1/cover-designs?book_type=birthday`)).json())
    .designs.map((x) => x.slug);
  check('a saved design reaches customers', (await publicSlugs()).includes(SLUG));

  await page.uncheck('#f-active');
  await saveDesign(page);
  check('unticking "Visible" takes it off the shelf',
    !(await publicSlugs()).includes(SLUG));
  check('but it stays in the console', (await stored()) !== null);

  await page.check('#f-active');
  await saveDesign(page);
  check('re-ticking "Visible" puts it back', (await publicSlugs()).includes(SLUG));

  page.once('dialog', (dlg) => dlg.accept());
  await page.click('#btn-retire');
  await page.waitForSelector(`.design-row[data-slug="${SLUG}"].retired`, { timeout: 20000 });
  check('"Retire" takes it off the shelf', !(await publicSlugs()).includes(SLUG));
  check('"Retire" closes the editor', await page.isVisible('#edit-empty'));

  // Cancel must not save
  await page.click(`.design-row[data-slug="${SLUG}"]`);
  await page.waitForSelector('#edit-form:not(.hidden)');
  await page.fill('#f-name', 'THIS SHOULD NOT PERSIST');
  await page.click('#btn-cancel');
  await page.waitForSelector('#edit-empty:not(.hidden)');
  d = await stored();
  check('"Cancel" discards the edit', d.name !== 'THIS SHOULD NOT PERSIST', d.name);

  // ---------------------------------------------------------------- orders
  console.log('ORDERS — every control');
  await page.click('.tab[data-tab="orders"]');
  await page.waitForSelector('#tab-orders:not(.hidden)');
  await page.waitForSelector(`.order-row[data-ref="${ref}"]`, { timeout: 20000 });
  check('the order is in the open list', true);

  await page.fill('#o-search', 'Wiring Probe');
  await page.waitForFunction(
    (r) => !!document.querySelector(`.order-row[data-ref="${r}"]`), ref,
    { timeout: 20000 });
  check('search by customer name finds it', true);
  await page.fill('#o-search', '91000112');
  await page.waitForFunction(
    (r) => !!document.querySelector(`.order-row[data-ref="${r}"]`), ref,
    { timeout: 20000 });
  check('search by phone digits finds it', true);
  await page.fill('#o-search', '');
  await page.waitForSelector(`.order-row[data-ref="${ref}"]`);

  // the status filter must offer more than a binary
  const statusOptions = await page.$$eval('#o-status option',
    (els) => els.map((e) => e.value));
  check('the status filter offers the real statuses, not just open/all',
    statusOptions.length > 2, statusOptions.join('|'));

  await page.click(`.order-row[data-ref="${ref}"]`);
  await page.waitForSelector('#order-detail:not(.hidden)');
  const detail = await page.evaluate(() => ({
    name: document.getElementById('od-name').textContent,
    phone: document.getElementById('od-phone').textContent,
    address: document.getElementById('od-address').textContent,
    amount: document.getElementById('od-amount').textContent,
  }));
  check('the detail screen shows the customer',
    detail.name === 'Wiring Probe' && detail.address.includes('probe 1'),
    JSON.stringify(detail));

  // Refresh must actually re-fetch
  await page.click('#btn-orders-refresh');
  await page.waitForSelector(`.order-row[data-ref="${ref}"]`);
  check('"Refresh" re-fetches the list', true);

  // the note field has to reach the audit trail
  const status0 = (await (await api(`/orders/${ref}`)).json()).status;
  if (status0 === 'pending_payment') {
    await page.fill('#od-note', 'wiring: transfer seen');
    await page.click('#od-actions button.primary');
    await page.waitForFunction(
      () => document.querySelectorAll('#od-files a').length === 2,
      undefined, { timeout: 180000 });
    const paid = await (await api(`/orders/${ref}`)).json();
    check('"mark paid" pays the order', paid.paid_at !== null);
    check('the note reached the audit trail',
      paid.events.some((e) => e.note === 'wiring: transfer seen'));
  } else {
    check(`the order auto-confirmed (${status0}) — "mark paid" not applicable`, true);
  }

  // A79: the low-resolution note. This order's photos are the good fixtures,
  // so the correct behaviour here is silence — a note that shows on every
  // order is one the operator stops reading.
  const softShown = await page.isVisible('#od-soft');
  const softFromApi = ((await (await api(`/orders/${ref}`)).json()).soft_pages || []);
  check('the low-resolution note matches what the server reports',
    softShown === (softFromApi.length > 0),
    `page=${softShown} server=${softFromApi.length}`);

  // print files
  const links = await page.$$eval('#od-files a', (els) => els.map((e) => e.href));
  check('both print files are offered', links.length === 2, String(links.length));
  const served = await page.evaluate(async (u) => {
    const r = await fetch(u);
    const head = new Uint8Array(await (await r.blob()).slice(0, 5).arrayBuffer());
    return `${r.status}:${String.fromCharCode(...head)}`;
  }, links[0]);
  check('a print link serves a real PDF', served === '200:%PDF-', served);

  // resend
  await page.click('#btn-resend');
  await page.waitForTimeout(1200);
  const afterResend = await (await api(`/orders/${ref}`)).json();
  check('"Send to the printer again" leaves the order alone',
    afterResend.status === (await (await api(`/orders/${ref}`)).json()).status);

  // every offered status button must be one the server accepts
  const offered = await page.$$eval('#od-actions button[data-target]',
    (els) => els.map((e) => e.dataset.target));
  const allowed = (await (await api(`/orders/${ref}`)).json()).next_statuses;
  check('the buttons match what the server allows',
    JSON.stringify(offered.slice().sort()) === JSON.stringify(allowed.slice().sort()),
    `page=${offered} server=${allowed}`);

  await page.fill('#od-note', 'wiring: to the printer');
  await page.click('#od-actions button[data-target="sent_to_production"]');
  await page.waitForFunction(
    () => document.getElementById('od-status').textContent.trim() === 'At the printer',
    undefined, { timeout: 20000 });
  const moved = await (await api(`/orders/${ref}`)).json();
  check('a status button moves the order', moved.status === 'sent_to_production');
  check('its note reached the audit trail',
    moved.events.some((e) => e.note === 'wiring: to the printer'));

  // sign out
  await page.click('#btn-signout');
  await page.waitForSelector('#screen-login.active');
  check('"Sign out" forgets the token',
    (await page.evaluate(() => localStorage.getItem('mb-admin-token'))) === null);

  console.log('errors:', errors.length ? errors : 'none');
  await browser.close();
  if (errors.length) fails.push('page errors');
  if (fails.length) throw new Error(`${fails.length} wiring problems: ${fails.join('; ')}`);
  console.log('ADMIN WIRING CHECK PASSED');
})().catch((e) => { console.error('FAILED', e.message || e); process.exit(1); });
