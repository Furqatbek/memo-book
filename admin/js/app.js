/* Admin console (A72).

   One job: manage the ready-made cover catalogue without SSH. The reason it
   is worth a UI rather than a CLI is the preview — placing a photo window by
   typing "19,24,110,110" and finding out at print time is exactly the loop
   this replaces. Here you drag the box over the real artwork.

   English only, deliberately: the audience is the founder, not customers.
   The five-language rule is about the people buying books. */
import * as api from './api.js?v=20260926e';
import { bindOrders, refreshOrders, resetOrders, when }
  from './orders.js?v=20260926e';

const TRIM_W = 148, TRIM_H = 210, SAFE = 5;   // the front panel, in mm

const S = {
  designs: [],
  editing: null,      // the design being edited, or null for a new one
  artworkFile: null,  // a File chosen but not yet uploaded
  artworkUrl: null,   // object URL for that file, so the preview is instant
  backArtworkFile: null,  // the same, for the optional back panel (A95)
  backArtworkUrl: null,
  clearBack: false,   // the operator asked to take the back artwork off
  bookTypes: [],
  artSpec: null,
  dirty: false,
  tab: 'orders',
};

const $ = (id) => document.getElementById(id);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const pct = (mm, total) => `${(mm / total) * 100}%`;

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.className = v;
    else if (k.startsWith('on') && typeof v === 'function') {
      el.addEventListener(k.slice(2).toLowerCase(), v);
    } else if (v !== null && v !== undefined) el.setAttribute(k, v);
  }
  for (const kid of kids) {
    if (kid !== null && kid !== undefined) el.append(kid);
  }
  return el;
}

function toast(message, kind = '') {
  const el = h('div', { class: `toast ${kind}` }, message);
  $('toasts').append(el);
  setTimeout(() => el.remove(), 4200);
}

function showScreen(name) {
  for (const id of ['screen-login', 'screen-main']) {
    $(id).classList.toggle('active', id === `screen-${name}`);
  }
}

/* ---------- sign in ---------- */

async function signIn(candidate) {
  const body = await api.ping(candidate);
  api.setToken(candidate);
  S.bookTypes = body.book_types || [];
  S.artSpec = body.artwork || null;
  renderTypeChecks();
  if (S.artSpec) {
    $('art-spec').textContent =
      `${S.artSpec.w_px} × ${S.artSpec.h_px} px `
      + `(${S.artSpec.w_mm} × ${S.artSpec.h_mm} mm at 300 dpi). `
      + `Minimum ${S.artSpec.min_w_px} × ${S.artSpec.min_h_px}. `
      + `The outer 16 mm folds around the board.`;
    $('back-spec').textContent =
      `Optional, and the mirror of the front: same ${S.artSpec.w_px} × `
      + `${S.artSpec.h_px} px, but the spine fold is the RIGHT edge, so let `
      + `the art bleed off the LEFT, top and bottom. Leave this empty and the `
      + `back prints in the flat colour below.`;
  }
  showScreen('main');
  showTab(S.tab);
  await Promise.all([refresh(), refreshOrders(deps)]);
}

/* One section on screen at a time. Orders first: it is the daily job, and
   designs are an occasional one. */
function showTab(name) {
  S.tab = name;
  for (const el of document.querySelectorAll('.tab')) {
    el.classList.toggle('active', el.dataset.tab === name);
  }
  for (const id of ['tab-orders', 'tab-designs', 'tab-telegram', 'tab-reviews',
                    'tab-funnel']) {
    $(id).classList.toggle('hidden', id !== `tab-${name}`);
  }
  // Loaded on arrival rather than at sign-in: most sessions never open these
  // tabs, and the lists are only interesting when you are looking at them.
  if (name === 'telegram') refreshOperators();
  if (name === 'reviews') refreshReviews();
  if (name === 'funnel') refreshFunnel();
}

/* ---------- Reviews (CR-003-9) ---------- */

/* A READING surface. It cannot edit and it cannot publish, and both of those
 * are the feature rather than an omission:
 *
 *   never publish without the permission box;
 *   never edit a review's wording;
 *   never invent one.
 *
 * The site's list is a hand-curated literal in assets/reviews.js. What this
 * page adds is the one genuinely tedious step — producing the exact entry to
 * paste — and it refuses to produce one for a review that did not grant
 * permission. A "copy" button that worked on those would be the rule broken
 * by convenience, which is how it would actually get broken.
 */
async function refreshReviews() {
  let body;
  try {
    body = await api.reviews();
  } catch (err) {
    return adminError(err, 'Could not load reviews.');
  }
  const rows = body.reviews || [];
  $('rv-empty').classList.toggle('hidden', rows.length > 0);

  const list = $('rv-list');
  list.innerHTML = '';
  for (const r of rows) {
    list.append(reviewRow(r));
  }
}

/* The entry to paste into assets/reviews.js, built from what they actually
 * wrote. Two decisions in here matter more than the formatting:
 *
 * QUOTED WITH JSON.stringify. Their own words, in Russian or Uzbek, very
 * often contain an apostrophe — and reviews.js is a file of single-quoted
 * literals. Hand-quoting would break the file that publishes the reviews.
 * It also escapes the newlines, so a two-paragraph review survives.
 *
 * THE FIELDS WE DO NOT KNOW ARE `null`, NOT PLACEHOLDER TEXT. `usable()` in
 * reviews.js requires name, photo, book and text, and drops an entry missing
 * any of them. So a snippet pasted unedited publishes NOTHING — which is the
 * right failure. The first version of this emitted
 * `book: "PAGES pages · WHAT IT WAS ABOUT"`, which is truthy: paste and
 * forget, and that string goes on the live site under a customer's name.
 */
function reviewSnippet(r) {
  const q = (v) => JSON.stringify(v == null ? '' : String(v));
  const lines = ['  {', `    name:  ${q(r.display_name || '')},`];
  if (r.city) lines.push(`    city:  ${q(r.city)},`);
  // Even when they sent a photo we cannot know what you will name the file.
  lines.push('    photo: null,   // REQUIRED: save their photo into '
             + 'assets/reviews/ and put "reviews/<filename>" here');
  lines.push('    book:  null,   // REQUIRED: e.g. "64 pages · a year in '
             + 'Samarkand"');
  lines.push(`    lang:  ${q(r.lang || 'ru')},`);
  lines.push(`    text:  ${q(r.text || '')} },`);
  return lines.join('\n');
}

function reviewRow(r) {
  const li = h('li', { class: `rv-row${r.may_publish ? '' : ' rv-private'}` });

  li.append(h('div', { class: 'rv-head' },
    h('b', {}, r.display_name || 'No name given'),
    r.city ? h('span', { class: 'muted small' }, r.city) : null,
    h('span', { class: 'muted small' }, r.human_ref),
    h('span', { class: 'muted small' }, when(r.submitted_at)),
    h('span', {
      class: `status-pill ${r.may_publish ? 'good' : 'off'}`,
      // Said in full, because this is the single fact the whole page turns
      // on and a pill alone is a thing people learn to stop reading.
      title: r.may_publish
        ? 'They ticked the box: this may be published, with the name above.'
        : 'They did NOT tick the box. This is a private message to us and '
          + 'must never appear on the site.',
    }, r.may_publish ? 'May publish' : 'Private')));

  /* Their words, exactly, in a block that preserves the line breaks they
     typed. Not truncated: a review shown as a fragment is one somebody
     "tidies" before pasting. */
  li.append(h('p', { class: 'rv-text' }, r.text || ''));

  if (r.lang) {
    li.append(h('p', { class: 'muted small' },
      `Written in: ${r.lang} — keep it in that language; the site marks it up `
      + 'so a screen reader reads it correctly.'));
  }

  if (r.photo_url) {
    li.append(h('a', {
      class: 'btn small', href: r.photo_url, target: '_blank', rel: 'noopener',
    }, 'Their photo'));
  }

  if (r.may_publish) {
    const pre = h('pre', { class: 'rv-snippet' }, reviewSnippet(r));
    const copy = h('button', { class: 'btn small', type: 'button' }, 'Copy entry');
    copy.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(reviewSnippet(r));
        toast('Entry copied. Paste it into assets/reviews.js.');
      } catch (e) {
        // No clipboard permission: the text is on screen to select anyway.
        toast('Select the text above and copy it.', 'warn');
      }
    });
    li.append(h('p', { class: 'muted small' },
      'Paste into assets/reviews.js, then fill in the two nulls. Until you '
      + 'do, the entry is dropped and nothing appears on the site — which is '
      + 'deliberate: a half-filled review must never publish itself. Three '
      + 'complete reviews are needed before the section replaces its honest '
      + 'note.'));
    li.append(pre);
    li.append(copy);
  } else {
    li.append(h('p', { class: 'muted small' },
      'No permission, so there is nothing to copy. Do not put this on the '
      + 'site, even reworded.'));
  }
  return li;
}

/* ---------- Where people stop (Change 3) ----------
 *
 * The report endpoint has existed since Change 3 and was read with curl. This
 * is the same payload on screen, and it earns its place by making two facts
 * impossible to miss rather than by drawing a nicer shape:
 *
 *   the top of the funnel is CLIENT-REPORTED, so it is a floor and not a
 *   count — an ad-blocker eats some of those rows;
 *   a rate with nothing above it reads "no data", never 0%.
 *
 * Both come straight out of the payload (`counting`, and `null` rates), and a
 * chart that renders them as a confident number and a confident zero is a
 * chart that lies about how much we know. So the caveat line is BUILT from
 * `counting` rather than typed here: if the server changes which steps come
 * from a browser, this follows without anybody remembering to.
 */

/* Everything in the payload that is not a funnel step. The step keys are the
   remainder, in FUNNEL_ORDER — Python dicts and JSON objects both keep
   insertion order, so the order of the funnel is the server's to decide and
   adding a step needs no change here. */
const FN_META = new Set(['conversion_rates', 'by_campaign', 'window', 'counting']);

const FN_LABELS = {
  site_visit: 'Saw the site',
  editor_opened: 'Opened the editor',
  book_started: 'Started a book',
  first_photo_uploaded: 'Uploaded a first photo',
  half_designed: 'Got half-designed',
  design_completed: 'Finished the design',
  preview_viewed: 'Looked at the preview',
  checkout_opened: 'Opened checkout',
  checkout_submitted: 'Submitted checkout',
  payment_succeeded: 'Paid',
};

// A step the server added and this file has not been taught yet still reads
// as something: "flip_video_generated" -> "Flip video generated".
function fnLabel(key) {
  if (FN_LABELS[key]) return FN_LABELS[key];
  const words = key.replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function fnSteps(body) {
  return Object.keys(body).filter((k) => !FN_META.has(k));
}

/* A rate, or the honest absence of one.
 *
 * `null` means the denominator was zero: nobody reached the step above, so
 * there is no rate to report. "0%" would be a claim that people arrived and
 * none of them converted — a different fact, and the one that sends you
 * rewriting a screen nobody reached.
 *
 * An actual zero therefore has to still read as "0%", which is why it is
 * spelled out rather than falling through the small-number branch as
 * "0.0%": the two have to look different from each other, not from nothing. */
function fnPct(rate) {
  if (rate === null || rate === undefined) return 'no data';
  if (rate === 0) return '0%';
  return `${(rate * 100).toFixed(rate < 0.1 ? 1 : 0)}%`;
}

async function refreshFunnel() {
  const query = {
    from: $('fn-from').value,
    to: $('fn-to').value,
    campaign: $('fn-campaign').value,
  };
  let body;
  try {
    body = await api.funnel(query);
  } catch (err) {
    return adminError(err, 'Could not load the funnel.');
  }

  const steps = fnSteps(body);
  // The server already computed every rate, including the null it uses for a
  // zero denominator. Recomputing any of them here would be a second opinion
  // that can disagree with the one the payload documents.
  const rates = body.conversion_rates || {};

  // Shown as soon as ANY step has a row — not just the top one, which is the
  // step most likely to have been eaten by an ad-blocker. With nothing at
  // all the steps are hidden too: ten zeroes and nine identical "nobody
  // reached the step above" lines say less than one sentence does.
  const any = steps.some((k) => (body[k] || 0) > 0);
  $('fn-empty').classList.toggle('hidden', any);
  $('fn-steps').classList.toggle('hidden', !any);
  renderFunnelCaveat(body, steps);

  const list = $('fn-steps');
  list.innerHTML = '';
  let previous = null;
  for (const key of steps) {
    const n = body[key] || 0;
    const stepRate = previous ? rates[`${previous.key}_to_${key}`] : undefined;
    list.append(fnRow(key, n, previous, stepRate,
                      rates[`${key}_of_site_visit`]));
    previous = { key, n };
  }

  renderFunnelCampaigns(body, steps);
}

function renderFunnelCaveat(body, steps) {
  const counting = body.counting || {};
  // Which steps the server says come from a browser — read off the payload,
  // so this cannot claim a different set from the one being counted.
  const reported = steps.filter(
    (k) => typeof counting[k] === 'string' && counting[k].includes('client'));
  const win = body.window || {};
  const when = (win.from || win.to)
    ? `${win.from ? shortDate(win.from) : 'the beginning'} to `
      + `${win.to ? shortDate(win.to) : 'now'}`
    : 'all time';

  const parts = [`Window: ${when} (dates are read as UTC, so a day here `
                 + 'starts at 05:00 in Tashkent).'];
  if (reported.length) {
    parts.push(`${reported.map(fnLabel).join(', ')} `
      + `${reported.length === 1 ? 'is' : 'are'} reported by the browser: an `
      + 'ad-blocker or a lost connection eats some of them, so those are a '
      + 'floor and not a count, and every rate measured against them reads '
      + 'BETTER than it is. Everything below is server-observed.');
  }
  parts.push('A step with nothing above it says "no data" rather than 0% — '
             + 'nobody arrived and nobody converted are different facts.');
  $('fn-caveat').textContent = parts.join(' ');
}

function fnRow(key, n, previous, stepRate, ofTop) {
  const li = h('li', { class: 'fn-step' });
  const share = ofTop === null || ofTop === undefined ? null : ofTop;
  li.append(h('div', { class: 'fn-line' },
    h('b', {}, fnLabel(key)),
    h('span', { class: 'fn-n' }, String(n)),
    h('span', { class: 'muted small' }, share === null
      ? 'share of the top: no data'
      : `${fnPct(share)} of the top`)));

  // The bar is the share of the top step. Capped for DRAWING only; the
  // number beside it is never capped, because a step that reads over 100%
  // is the under-count above it showing itself and must stay visible.
  li.append(h('div', { class: 'fn-bar' },
    h('span', {
      class: 'fn-fill', style: `width:${Math.min(share ?? 0, 1) * 100}%`,
    })));

  if (previous) {
    li.append(h('div', { class: 'muted small' },
      fnDropText(previous, n, stepRate)));
  }
  return li;
}

/* What happened between the step above and this one. Three cases, and the
   third is the one a tidier chart would hide: a step can legitimately exceed
   the one above it, because the steps above it are client-reported and
   under-counted. Rendering that as a negative drop-off, or clamping it to
   zero, would bury the only signal we get that the top is missing rows. */
function fnDropText(previous, n, stepRate) {
  if (stepRate === null || stepRate === undefined) {
    return `No data: nobody reached "${fnLabel(previous.key)}" in this window.`;
  }
  if (n > previous.n) {
    return `${fnPct(stepRate)} of "${fnLabel(previous.key)}" — MORE than the `
      + 'step above, which is only possible because that step is '
      + 'client-reported and under-counted. Trust this number, not the rate.';
  }
  const lost = previous.n - n;
  if (!lost) return `${fnPct(stepRate)} carried on — nobody stopped here.`;
  return `${fnPct(stepRate)} carried on — ${lost} `
    + `${lost === 1 ? 'person' : 'people'} stopped here.`;
}

/* Per campaign, because one number for the whole site cannot tell you which
   channel paid for itself — which is the arithmetic this instrumentation
   exists for. */
function renderFunnelCampaigns(body, steps) {
  const byCampaign = body.by_campaign || {};
  const names = Object.keys(byCampaign);
  $('fn-campaigns').classList.toggle('hidden', names.length === 0);

  // The select is only repopulated from an UNFILTERED answer, which is the
  // one that lists every campaign in the window. Rebuilding it from a
  // filtered answer would leave one option and no way back.
  if (!body.window || !body.window.campaign) {
    const select = $('fn-campaign');
    const chosen = select.value;
    select.innerHTML = '';
    select.append(h('option', { value: '' }, 'All campaigns'));
    for (const name of names) {
      select.append(h('option', { value: name }, name));
    }
    select.value = names.includes(chosen) ? chosen : '';
  }

  /* The paid rate sits SECOND, beside the name, not at the far end past ten
     step columns. Ten columns do not fit a screen, and the one number this
     table exists to produce — what a channel actually converts — was the one
     you had to scroll to find. */
  const head = $('fn-ch-head');
  head.innerHTML = '';
  head.append(h('th', {}, 'Campaign'), h('th', {}, 'Paid / saw the site'));
  for (const key of steps) head.append(h('th', {}, fnLabel(key)));

  const bodyEl = $('fn-ch-body');
  bodyEl.innerHTML = '';
  const last = steps[steps.length - 1];
  for (const name of names) {
    const row = byCampaign[name] || {};
    const counts = row.counts || {};
    const tr = h('tr', {}, h('td', {}, name),
      h('td', { class: 'fn-rate' },
        fnPct((row.conversion_rates || {})[`${last}_of_site_visit`])));
    for (const key of steps) tr.append(h('td', {}, String(counts[key] || 0)));
    bodyEl.append(tr);
  }
}

/* ---------- Telegram (A97) ---------- */

async function refreshOperators() {
  let body;
  try {
    body = await api.listOperators();
  } catch (err) {
    return adminError(err, 'Could not load linked accounts.');
  }
  $('tg-webhook-warn').classList.toggle('hidden', body.webhook_configured);

  const list = $('tg-operators');
  list.innerHTML = '';
  const rows = body.operators || [];
  $('tg-empty').classList.toggle('hidden', rows.length > 0);
  for (const op of rows) {
    const who = op.display_name || op.username || `id ${op.telegram_user_id}`;
    const meta = [op.username ? `@${op.username}` : null,
                  `id ${op.telegram_user_id}`,
                  op.last_used_at ? `last used ${shortDate(op.last_used_at)}`
                    : 'never used'].filter(Boolean).join(' · ');
    const row = h('div', { class: 'tg-op' },
      h('span', { class: 'row-meta' }, h('b', {}, who),
        h('span', { class: 'muted small' }, meta)));
    const remove = h('button', { class: 'btn small danger', type: 'button' },
                     'Remove');
    remove.addEventListener('click', () => revokeOperator(op, who));
    row.append(remove);
    list.append(row);
  }

  // Ids from .env cannot be removed from here, so say where they live
  // rather than leaving a Remove button that would not work.
  const env = body.env_user_ids || [];
  $('tg-env').classList.toggle('hidden', env.length === 0);
  if (env.length) {
    $('tg-env').textContent =
      `Also allowed from the server's .env, and not removable here: `
      + `${env.join(', ')}. Clear TELEGRAM_CONTROL_USER_IDS to drop them.`;
  }
}

function shortDate(value) {
  try {
    return new Date(value).toLocaleDateString(undefined,
      { day: 'numeric', month: 'short' });
  } catch { return '?'; }
}

async function revokeOperator(op, who) {
  if (!confirm(`Remove ${who}?\n\n`
    + 'That account stops being able to move orders from Telegram. '
    + 'It can be linked again with a new code.')) return;
  try {
    await api.revokeOperator(op.telegram_user_id);
    toast('Removed.');
    await refreshOperators();
  } catch (err) {
    await adminError(err, 'Could not remove.');
  }
}

async function newLinkCode() {
  $('tg-new-code').disabled = true;
  try {
    const body = await api.newLinkCode();
    $('tg-code').textContent = body.code;
    $('tg-code-box').classList.remove('hidden');
    // Date AND time: the code now outlives the day it was made, so a bare
    // clock time would not say which day it means.
    $('tg-code-expiry').textContent =
      `Valid until ${new Date(body.expires_at).toLocaleString(undefined, {
        weekday: 'short', day: 'numeric', month: 'short',
        hour: '2-digit', minute: '2-digit' })}.`;
    // Issuing invalidates any previous code, so the warning above may have
    // just become relevant — and the list may be stale.
    await refreshOperators();
  } catch (err) {
    await adminError(err, 'Could not make a code.');
  } finally {
    $('tg-new-code').disabled = false;
  }
}

/* What the orders section needs from here, passed in rather than imported
   back, so the two files stay one-directional. */
const deps = { toast, signOut: () => signOut(), adminError };

function signOut() {
  api.setToken(null);
  S.designs = [];
  S.editing = null;
  resetOrders();
  showScreen('login');
  $('login-token').value = '';
}

/* Every refusal the admin API can give is a 404, deliberately (A72) — which
   means a dead token and a missing row look identical from here. On a 404
   against one resource, ask whether the session itself is still good: if the
   ping fails too, sign out rather than leave the operator clicking at a
   console that will never work again. */
async function adminError(e, fallback) {
  if (e.status === 404) {
    try {
      await api.ping(api.token());
    } catch {
      toast('Your session ended — sign in again.', 'warn');
      signOut();
      return;
    }
  }
  toast(e.message || fallback, 'warn');
}

/* Every rejection the server can give is a 404, so there is one honest
   thing to say and it covers all three causes. */
const SIGN_IN_HELP =
  'That token was not accepted. Either it is wrong, or ADMIN_TOKEN is not '
  + 'set on the server — with it empty the admin API is switched off.';

/* ---------- the list ---------- */

async function refresh() {
  try {
    const body = await api.listDesigns();
    S.designs = body.designs || [];
  } catch (e) {
    if (e.status === 404) return signOut();
    toast(e.message || 'Could not load designs.', 'warn');
    return;
  }
  renderList();
}

function renderList() {
  const list = $('design-list');
  list.innerHTML = '';
  $('list-empty').classList.toggle('hidden', S.designs.length > 0);
  for (const d of S.designs) {
    const card = h('button', {
      class: 'design-row' + (S.editing && S.editing.design_id === d.design_id
        ? ' active' : '') + (d.active ? '' : ' retired'),
      type: 'button', 'data-slug': d.slug,
      onclick: () => edit(d),
    });
    card.append(h('img', { src: d.thumb_url, alt: '', loading: 'lazy' }));
    const meta = h('span', { class: 'row-meta' });
    meta.append(h('b', {}, d.name || d.slug));
    meta.append(h('span', { class: 'muted small' },
                  (d.book_types.length ? d.book_types.join(', ') : 'any occasion')
                  + (d.photo_rect ? ' · photo' : ' · artwork only')));
    if (!d.active) meta.append(h('span', { class: 'pill' }, 'retired'));
    card.append(meta);
    list.append(card);
  }
}

function renderTypeChecks() {
  const box = $('f-types');
  box.innerHTML = '';
  for (const t of S.bookTypes) {
    box.append(h('label', { class: 'check' },
      h('input', { type: 'checkbox', value: t, 'data-type': t }),
      h('span', {}, t)));
  }
  box.addEventListener('change', () => markDirty());
}

/* ---------- the form ---------- */

const BLANK = {
  design_id: null, slug: '', name: '', book_types: [], photo_rect: null,
  title: { x_mm: 74, y_mm: 168, size_pt: 26 }, title_color: null,
  bg_color: '#ffffff', sort_order: 100, active: true,
  display_url: null, back_display_url: null,
};

function edit(design) {
  S.editing = design ? { ...design } : { ...BLANK };
  S.artworkFile = null;
  if (S.artworkUrl) { URL.revokeObjectURL(S.artworkUrl); S.artworkUrl = null; }
  S.backArtworkFile = null;
  if (S.backArtworkUrl) {
    URL.revokeObjectURL(S.backArtworkUrl);
    S.backArtworkUrl = null;
  }
  S.clearBack = false;
  S.dirty = false;
  $('edit-empty').classList.add('hidden');
  $('edit-form').classList.remove('hidden');
  $('f-artwork').value = '';
  $('art-note').classList.add('hidden');
  $('f-back-artwork').value = '';
  $('back-note').classList.add('hidden');

  const d = S.editing;
  $('f-slug').value = d.slug || '';
  // The slug names this design's files in storage, and editing a design
  // cannot move them — so on an existing one it is shown, not offered. A
  // field that accepted a new value and silently kept the old one would be
  // worse than no field.
  $('f-slug').disabled = !!d.design_id;
  $('slug-hint').textContent = d.design_id
    ? 'Fixed once created — it names the artwork in storage. Change the name '
      + 'above instead.'
    : 'Stable id. Re-using an existing one replaces that design.';
  $('f-name').value = d.name || '';
  for (const cb of $('f-types').querySelectorAll('input')) {
    cb.checked = (d.book_types || []).includes(cb.value);
  }
  $('f-has-photo').checked = !!d.photo_rect;
  $('f-rect').classList.toggle('off', !d.photo_rect);
  const rect = d.photo_rect || { x_mm: 19, y_mm: 24, w_mm: 110, h_mm: 110 };
  $('f-rect-x').value = rect.x_mm;
  $('f-rect-y').value = rect.y_mm;
  $('f-rect-w').value = rect.w_mm;
  $('f-rect-h').value = rect.h_mm;
  $('f-has-title').checked = !!d.title;
  $('f-title').classList.toggle('off', !d.title);
  const title = d.title || BLANK.title;
  $('f-title-x').value = title.x_mm;
  $('f-title-y').value = title.y_mm;
  $('f-title-size').value = title.size_pt || 26;
  $('f-title-color').value = d.title_color || '#ffffff';
  $('f-title-color').dataset.auto = d.title_color ? '' : '1';
  $('f-bg').value = d.bg_color || '#ffffff';
  $('f-order').value = d.sort_order ?? 100;
  $('f-active').checked = d.active !== false;
  $('btn-retire').classList.toggle('hidden', !d.design_id);
  $('f-title-auto').classList.toggle('on', !d.title_color);

  renderPreview();
  renderList();
}

function closeEditor() {
  S.editing = null;
  S.artworkFile = null;
  if (S.artworkUrl) { URL.revokeObjectURL(S.artworkUrl); S.artworkUrl = null; }
  S.backArtworkFile = null;
  if (S.backArtworkUrl) {
    URL.revokeObjectURL(S.backArtworkUrl);
    S.backArtworkUrl = null;
  }
  S.clearBack = false;
  $('edit-form').classList.add('hidden');
  $('edit-empty').classList.remove('hidden');
  renderList();
}

const markDirty = () => { S.dirty = true; };

/* The human name of a field, for an error that names it. */
function labelFor(el) {
  const owner = el.closest('label, fieldset');
  const span = owner && owner.querySelector('span');
  return (span && span.textContent.trim()) || el.id.replace(/^f-/, '');
}

function readRect() {
  if (!$('f-has-photo').checked) return null;
  return {
    x_mm: Number($('f-rect-x').value) || 0,
    y_mm: Number($('f-rect-y').value) || 0,
    w_mm: Math.max(1, Number($('f-rect-w').value) || 1),
    h_mm: Math.max(1, Number($('f-rect-h').value) || 1),
  };
}

/* Null when the design carries no title at all — artwork that already has
   its own lettering, where a second title drawn on top is exactly wrong.
   The backend and `cover_design.py --title` have always allowed this; the
   console was the one place that could not express it (A90). */
function readTitle() {
  if (!$('f-has-title').checked) return null;
  return {
    x_mm: Number($('f-title-x').value) || 0,
    y_mm: Number($('f-title-y').value) || 0,
    size_pt: Math.max(4, Number($('f-title-size').value) || 26),
  };
}

const titleColor = () =>
  ($('f-title-color').dataset.auto ? null : $('f-title-color').value);

/* ---------- preview ---------- */

function renderPreview() {
  const d = S.editing;
  if (!d) return;
  const cover = $('cover');
  cover.style.background = $('f-bg').value || '#ffffff';

  const art = $('cover-art');
  const src = S.artworkUrl || d.display_url || '';
  art.classList.toggle('hidden', !src);
  if (src && art.getAttribute('src') !== src) art.setAttribute('src', src);
  else if (!src) art.removeAttribute('src');

  // The back panel, shown only when this design has one — a newly picked
  // file, or one already saved and not being removed (A95).
  const backSrc = S.clearBack ? '' : (S.backArtworkUrl || d.back_display_url || '');
  const backArt = $('back-art');
  $('back-col').classList.toggle('hidden', !backSrc);
  $('back-cover').style.background = $('f-bg').value || '#ffffff';
  $('f-back-clear').classList.toggle('hidden', !backSrc);
  if (backSrc && backArt.getAttribute('src') !== backSrc) {
    backArt.setAttribute('src', backSrc);
  } else if (!backSrc) backArt.removeAttribute('src');

  const rect = readRect();
  const box = $('cover-photo');
  box.classList.toggle('hidden', !rect);
  if (rect) {
    box.style.left = pct(rect.x_mm, TRIM_W);
    box.style.top = pct(rect.y_mm, TRIM_H);
    box.style.width = pct(rect.w_mm, TRIM_W);
    box.style.height = pct(rect.h_mm, TRIM_H);
  }

  const title = readTitle();
  const el = $('cover-title');
  el.classList.toggle('hidden', !title);
  if (!title) return;
  el.style.left = pct(title.x_mm, TRIM_W);
  el.style.top = pct(title.y_mm, TRIM_H);
  // In real px, not a percentage: a percentage font-size resolves against the
  // parent's font size, not the width, and would show the title at the wrong
  // scale entirely. 1pt = 25.4/72 mm.
  const perMm = cover.clientWidth / TRIM_W;
  el.style.fontSize = `${Math.max(6, title.size_pt * (25.4 / 72) * perMm)}px`;
  el.style.color = titleColor() || autoInk($('f-bg').value);
}

/* Mirrors backend/app/render/cover.py:auto_title_color, so "Auto" shows the
   ink that will actually print. */
function autoInk(bg) {
  const m = /^#([0-9a-f]{6})$/i.exec(bg || '#ffffff');
  if (!m) return '#1a1a1a';
  const n = parseInt(m[1], 16);
  const r = n >> 16, g = (n >> 8) & 255, b = n & 255;
  return (0.299 * r + 0.587 * g + 0.114 * b) > 140 ? '#1a1a1a' : '#ffffff';
}

/* Drag a box around the cover, in mm. `onMove` receives the new position and
   decides what to do with it — the photo window moves, the title marker
   moves, the corner handle resizes. */
function draggable(el, onMove, { handle = null } = {}) {
  const target = handle || el;
  target.addEventListener('pointerdown', (e) => {
    if (!e.isPrimary) return;
    e.preventDefault();
    e.stopPropagation();
    const cover = $('cover').getBoundingClientRect();
    const perMmX = cover.width / TRIM_W;
    const perMmY = cover.height / TRIM_H;
    const start = { x: e.clientX, y: e.clientY };
    const move = (ev) => {
      onMove((ev.clientX - start.x) / perMmX, (ev.clientY - start.y) / perMmY);
      renderPreview();
      markDirty();
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });
}

function wirePreviewDragging() {
  const box = $('cover-photo');
  let origin = null;
  const grab = () => {
    origin = readRect();
  };
  box.addEventListener('pointerdown', grab, true);
  draggable(box, (dx, dy) => {
    if (!origin) return;
    $('f-rect-x').value = Math.round(clamp(origin.x_mm + dx, -30, TRIM_W));
    $('f-rect-y').value = Math.round(clamp(origin.y_mm + dy, -30, TRIM_H));
  });
  const handle = box.querySelector('.rs.se');
  handle.addEventListener('pointerdown', grab, true);
  draggable(box, (dx, dy) => {
    if (!origin) return;
    $('f-rect-w').value = Math.round(clamp(origin.w_mm + dx, 10, TRIM_W + 30));
    $('f-rect-h').value = Math.round(clamp(origin.h_mm + dy, 10, TRIM_H + 30));
  }, { handle });

  const title = $('cover-title');
  let titleOrigin = null;
  title.addEventListener('pointerdown', () => { titleOrigin = readTitle(); }, true);
  draggable(title, (dx, dy) => {
    if (!titleOrigin) return;
    $('f-title-x').value = Math.round(clamp(titleOrigin.x_mm + dx, SAFE, TRIM_W - SAFE));
    $('f-title-y').value = Math.round(clamp(titleOrigin.y_mm + dy, SAFE, TRIM_H - SAFE));
  });
}

/* ---------- saving ---------- */

async function save(e) {
  e.preventDefault();
  const d = S.editing;
  if (!d) return;
  // Nothing below runs if the browser rejects the form first, and its own
  // message for a number field is unhelpful — so check ourselves and say
  // which field is wrong. A Save button that does nothing is the worst
  // possible answer.
  const bad = $('edit-form').querySelector(':invalid');
  if (bad) {
    bad.focus();
    return toast(`Check the ${labelFor(bad)} field — ${bad.validationMessage}`,
                 'warn');
  }
  const slug = $('f-slug').value.trim();
  if (!slug) return toast('A slug is needed — it identifies the design.', 'warn');

  const types = [...$('f-types').querySelectorAll('input')]
    .filter((cb) => cb.checked).map((cb) => cb.value);
  const fields = {
    slug,
    name: $('f-name').value.trim(),
    book_types: types.join(','),
    photo_rect: JSON.stringify(readRect()),
    title: JSON.stringify(readTitle()),
    title_color: titleColor() || '',
    bg_color: $('f-bg').value,
    sort_order: String(Number($('f-order').value) || 100),
  };

  $('btn-save').disabled = true;
  try {
    let saved;
    if (S.artworkFile) {
      saved = await api.saveDesign(fields, S.artworkFile, S.backArtworkFile);
      if (S.clearBack && !S.backArtworkFile) {
        saved = await api.patchDesign(saved.design_id, { clear_back: true });
      }
      // The upload endpoint always makes a design visible; honour the switch.
      if (!$('f-active').checked) {
        saved = await api.retireDesign(saved.design_id);
      }
    } else if (d.design_id) {
      saved = await api.patchDesign(d.design_id, {
        name: fields.name,
        book_types: types,
        photo_rect: readRect(),
        title: readTitle(),
        title_color: titleColor(),
        bg_color: fields.bg_color,
        sort_order: Number(fields.sort_order),
        active: $('f-active').checked,
        clear_back: S.clearBack && !S.backArtworkFile,
      });
      // A back added to a design whose front is unchanged goes on its own,
      // so the front file is never re-uploaded just to carry it (A95).
      if (S.backArtworkFile) {
        saved = await api.saveBackArtwork(d.design_id, S.backArtworkFile);
      }
    } else {
      return toast('Choose an artwork file for this new design.', 'warn');
    }
    toast(`Saved “${saved.name || saved.slug}”.`);
    await refresh();
    const fresh = S.designs.find((x) => x.design_id === saved.design_id);
    edit(fresh || saved);
  } catch (err) {
    await adminError(err, 'Could not save.');
  } finally {
    $('btn-save').disabled = false;
  }
}

async function retire() {
  const d = S.editing;
  if (!d || !d.design_id) return;
  if (!confirm(`Retire “${d.name || d.slug}”?\n\n`
    + 'It stops being offered to new customers. Books already ordered with '
    + 'it keep their cover and keep printing.')) return;
  try {
    await api.retireDesign(d.design_id);
    toast('Retired.');
    await refresh();
    closeEditor();
  } catch (err) {
    await adminError(err, 'Could not retire.');
  }
}

/* ---------- wiring ---------- */

function bind() {
  $('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const err = $('login-error');
    err.classList.add('hidden');
    try {
      await signIn($('login-token').value.trim());
    } catch (ex) {
      err.textContent = ex.status === 0
        ? 'No connection to the server.' : SIGN_IN_HELP;
      err.classList.remove('hidden');
    }
  });
  $('btn-signout').addEventListener('click', signOut);
  for (const el of document.querySelectorAll('.tab')) {
    el.addEventListener('click', () => showTab(el.dataset.tab));
  }
  bindOrders(deps);
  $('tg-new-code').addEventListener('click', newLinkCode);
  $('fn-refresh').addEventListener('click', refreshFunnel);
  // The campaign picker refetches rather than filtering what is on screen:
  // the per-campaign counts are computed by the server, and a client-side
  // filter would have to re-derive the rates and would get them wrong.
  $('fn-campaign').addEventListener('change', refreshFunnel);
  $('btn-new').addEventListener('click', () => edit(null));
  $('btn-cancel').addEventListener('click', closeEditor);
  $('btn-retire').addEventListener('click', retire);
  $('edit-form').addEventListener('submit', save);

  /* Warn about the size and aspect before upload, not after print. Shared
     by both pickers: the back panel is held to exactly the same spec as the
     front, so the two must say the same things about the same file (A95). */
  function noteArtworkProblems(url, note) {
    const probe = new Image();
    probe.onload = () => {
      const want = (S.artSpec ? S.artSpec.w_px / S.artSpec.h_px : 164 / 242);
      const got = probe.width / probe.height;
      const tooSmall = S.artSpec
        && (probe.width < S.artSpec.min_w_px || probe.height < S.artSpec.min_h_px);
      if (tooSmall) {
        note.textContent = `${probe.width} × ${probe.height} px is below the `
          + `minimum ${S.artSpec.min_w_px} × ${S.artSpec.min_h_px} — this would `
          + `print soft, and the server will refuse it.`;
        note.classList.remove('hidden');
      } else if (Math.abs(got - want) / want > 0.02) {
        note.textContent = `This file is ${probe.width} × ${probe.height} px. `
          + `It will be centre-cropped to fit the cover shape.`;
        note.classList.remove('hidden');
      } else {
        note.classList.add('hidden');
      }
      renderPreview();
    };
    probe.src = url;
  }

  $('f-artwork').addEventListener('change', (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    S.artworkFile = file;
    if (S.artworkUrl) URL.revokeObjectURL(S.artworkUrl);
    S.artworkUrl = URL.createObjectURL(file);
    markDirty();
    noteArtworkProblems(S.artworkUrl, $('art-note'));
    renderPreview();
  });

  $('f-back-artwork').addEventListener('change', (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    S.backArtworkFile = file;
    S.clearBack = false;      // choosing a file is the opposite of removing one
    if (S.backArtworkUrl) URL.revokeObjectURL(S.backArtworkUrl);
    S.backArtworkUrl = URL.createObjectURL(file);
    markDirty();
    noteArtworkProblems(S.backArtworkUrl, $('back-note'));
    renderPreview();
  });

  $('f-back-clear').addEventListener('click', () => {
    S.backArtworkFile = null;
    S.clearBack = true;
    if (S.backArtworkUrl) {
      URL.revokeObjectURL(S.backArtworkUrl);
      S.backArtworkUrl = null;
    }
    $('f-back-artwork').value = '';
    $('back-note').classList.add('hidden');
    markDirty();
    renderPreview();
  });

  for (const id of ['f-rect-x', 'f-rect-y', 'f-rect-w', 'f-rect-h',
                    'f-title-x', 'f-title-y', 'f-title-size']) {
    $(id).addEventListener('input', () => { markDirty(); renderPreview(); });
  }
  $('f-has-photo').addEventListener('change', () => {
    $('f-rect').classList.toggle('off', !$('f-has-photo').checked);
    markDirty();
    renderPreview();
  });
  $('f-has-title').addEventListener('change', () => {
    $('f-title').classList.toggle('off', !$('f-has-title').checked);
    markDirty();
    renderPreview();
  });
  $('f-bg').addEventListener('input', () => { markDirty(); renderPreview(); });
  $('f-title-color').addEventListener('input', () => {
    $('f-title-color').dataset.auto = '';
    $('f-title-auto').classList.remove('on');
    markDirty();
    renderPreview();
  });
  $('f-title-auto').addEventListener('click', () => {
    $('f-title-color').dataset.auto = '1';
    $('f-title-auto').classList.add('on');
    markDirty();
    renderPreview();
  });
  for (const id of ['f-name', 'f-slug', 'f-order', 'f-active']) {
    $(id).addEventListener('input', markDirty);
  }

  wirePreviewDragging();

  // The title is sized in px from the cover's measured width, so a resize
  // has to redraw it.
  window.addEventListener('resize', () => { if (S.editing) renderPreview(); });

  window.addEventListener('beforeunload', (e) => {
    if (S.editing && S.dirty) { e.preventDefault(); e.returnValue = ''; }
  });
}

async function boot() {
  bind();
  const existing = api.token();
  if (existing) {
    try {
      await signIn(existing);
      return;
    } catch { api.setToken(null); }
  }
  showScreen('login');
}

boot();
