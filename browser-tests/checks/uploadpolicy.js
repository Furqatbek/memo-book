/* The upload cap, as a browser experiences it.
 *
 * The backend suite proves the signed policy CONTAINS a
 * content-length-range. It cannot prove the browser sends the policy back,
 * because that half lives in api.js and contribute.js — and a form that
 * drops one field, or puts the file before the fields, fails in a way no
 * Python test would notice.
 *
 * So this drives the real thing and asserts what can honestly be observed:
 *
 *   - the upload is a POST, never a PUT;
 *   - the browser wrote its own multipart boundary (setting a Content-Type
 *     header by hand destroys the body);
 *   - the object LANDED AT THE KEY THE SERVER SIGNED. That is the evidence
 *     the signed fields were forwarded: the key is not in the URL for a
 *     POST, it comes from a form field, and a form that dropped the fields
 *     fails outright rather than landing somewhere else. Measured.
 *
 * TWO THINGS THIS DELIBERATELY DOES NOT CLAIM, both measured rather than
 * assumed:
 *
 *   - that an oversized upload is REFUSED. The dev server is moto, and moto
 *     does not enforce content-length-range; a 5KB body sailed through a
 *     100-byte policy. Asserting a rejection here would pass against a mock
 *     that rejects nothing, which is worse than no assertion — it would
 *     read for ever as proof of something untrue.
 *   - that the file part is LAST. Real S3 stops reading the form there, so
 *     the ordering matters; moto does not parse strictly enough to notice,
 *     so there is nothing here to assert it against. The ordering is
 *     enforced by the one place that writes the form, in api.js and
 *     contribute.js, and is stated in a comment at each.
 *
 * Nor can the form body be read back: Chromium streams a multipart body
 * containing a file, and Playwright's postData()/postDataBuffer() both hand
 * back nothing for it. That is why the evidence above is the landing key
 * rather than the bytes of the request.
 *
 *   node checks/uploadpolicy.js
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

/* Watch requests that go to storage rather than to the API. The body is
   not recorded: Chromium streams a multipart body containing a file and
   Playwright exposes nothing for it, so pretending otherwise would just
   produce assertions that always pass or always fail. */
function watchUploads(page, seen) {
  page.on('request', (req) => {
    const url = req.url();
    if (!/:9421|amazonaws|\/memobook/.test(url)) return;
    if (!['POST', 'PUT'].includes(req.method())) return;
    seen.push({ method: req.method(), url, headers: req.headers() });
  });
}

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const errors = [];

  /* ---------------- the owner, uploading in the editor ---------------- */
  const owner = await (await browser.newContext({
    viewport: { width: 1360, height: 850 },
  })).newPage();
  const noise = watchPage(owner, errors);
  const uploads = [];
  watchUploads(owner, uploads);

  console.log('THE OWNER’S UPLOAD');
  await owner.goto(`${BASE}/editor/`);
  await owner.waitForSelector('.btype:not([disabled])', { timeout: 15000 });
  await owner.click('.btype[data-btype="memory"]');
  await owner.waitForSelector('.tier:not([disabled])', { timeout: 10000 });
  await owner.click('.tier[data-tier="16"]');
  await owner.waitForSelector('#screen-editor.active, #design-step:not(.hidden)');
  if (await owner.isVisible('#design-step')) await owner.click('#design-skip');
  await owner.waitForSelector('#screen-editor.active', { timeout: 15000 });

  /* What the server signed, read from the API rather than guessed. */
  const issued = await owner.evaluate(async () => {
    const c = JSON.parse(localStorage.getItem('mb-book'));
    const r = await fetch(`/api/v1/books/${c.book_id}/photos/upload-url`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Edit-Token': c.edit_token },
      body: JSON.stringify({ filename: 'a.jpg', mime: 'image/jpeg', bytes: 5000 }),
    });
    return r.json();
  });
  check('  the server signs a POST target', !!(issued.upload && issued.upload.url),
    issued.upload && issued.upload.url);
  const signedFields = Object.keys(issued.upload.fields);
  check('  with a policy and a signature',
    signedFields.includes('policy') && signedFields.includes('x-amz-signature'),
    signedFields.join(','));

  /* Now the real upload through the editor's own code path. */
  await owner.setInputFiles('#file-input', PHOTO);
  await owner.waitForFunction(
    () => document.querySelectorAll('.ph-card img').length >= 1,
    { timeout: 40000 });

  const sent = uploads.filter((u) => u.method === 'POST');
  check('  the bytes go up as a POST', sent.length >= 1,
    uploads.map((u) => u.method).join(',') || 'nothing seen');
  check('  and never as a PUT',
    !uploads.some((u) => u.method === 'PUT'),
    uploads.map((u) => u.method).join(','));

  if (sent.length) {
    const ct = sent[0].headers['content-type'] || '';
    check('  the browser wrote its own multipart boundary',
      ct.startsWith('multipart/form-data') && ct.includes('boundary='), ct);
  }

  /* The object landed where the POLICY said it would. For a POST the key
     comes from a form field, not the URL, so this is the observable proof
     that the signed fields were forwarded — a form without them fails
     outright rather than landing elsewhere. */
  const landed = await owner.evaluate(async () => {
    const c = JSON.parse(localStorage.getItem('mb-book'));
    const r = await fetch(`/api/v1/books/${c.book_id}/photos`,
                          { headers: { 'X-Edit-Token': c.edit_token } });
    return (await r.json()).photos.map((p) => [p.status, !!p.thumb_url]);
  });
  check('  the photo ingested, so the bytes landed at the signed key',
    landed.some(([status, thumb]) => status === 'ready' && thumb),
    JSON.stringify(landed));

  /* ------------- the contributor, on a page of their own ------------- */
  console.log('\nTHE CONTRIBUTOR’S UPLOAD');
  const token = await owner.evaluate(async () => {
    const c = JSON.parse(localStorage.getItem('mb-book'));
    const r = await fetch(`/api/v1/books/${c.book_id}/contributor-link`, {
      method: 'POST', headers: { 'X-Edit-Token': c.edit_token },
    });
    return (await r.json()).contributor_token;
  });
  const friend = await (await browser.newContext()).newPage();
  const friendNoise = watchPage(friend, errors);
  const friendUploads = [];
  watchUploads(friend, friendUploads);

  await friend.goto(`${BASE}/c/${token}`);
  await friend.waitForSelector('#c-files', { timeout: 20000 });
  await friend.setInputFiles('#c-files', PHOTO);
  await friend.waitForFunction(
    () => /added/i.test(document.getElementById('c-status').textContent),
    { timeout: 40000 });

  const fsent = friendUploads.filter((u) => u.method === 'POST');
  check('  the bytes go up as a POST', fsent.length >= 1,
    friendUploads.map((u) => u.method).join(',') || 'nothing seen');
  check('  and never as a PUT',
    !friendUploads.some((u) => u.method === 'PUT'),
    friendUploads.map((u) => u.method).join(','));
  if (fsent.length) {
    const ct = fsent[0].headers['content-type'] || '';
    check('  with the browser’s own multipart boundary',
      ct.startsWith('multipart/form-data') && ct.includes('boundary='), ct);
  }
  /* Wait for the count to refresh, then read the LEADING number. A bare
     /[1-9]/ over this line matches the "100" in "room for 100 more" and
     passes while the count still says zero — which it did. */
  const leading = () => friend.evaluate(() => {
    const m = /^\s*(\d+)/.exec(
      document.getElementById('c-sub').textContent || '');
    return m ? Number(m[1]) : -1;
  });
  await friend.waitForFunction(
    () => /^\s*[1-9]/.test(document.getElementById('c-sub').textContent || ''),
    { timeout: 20000 }).catch(() => {});
  const added = await leading();
  check('  and the book counts it', added >= 1, `count=${added}`);

  console.log('\nerrors:', errors.length ? errors : 'none');
  const ignored = noise.length + friendNoise.length;
  if (ignored) {
    console.log(`ignored ${ignored} resource-load line(s) — see checks/_watch.js`);
  }
  await browser.close();
  if (errors.length || failed) {
    console.error(`UPLOAD POLICY CHECK FAILED (${failed} checks)`);
    process.exit(1);
  }
  console.log('UPLOAD POLICY CHECK PASSED');
})().catch((e) => { console.error('FAILED', e); process.exit(1); });
