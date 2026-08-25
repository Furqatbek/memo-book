/* Admin console (A72).

   One job: manage the ready-made cover catalogue without SSH. The reason it
   is worth a UI rather than a CLI is the preview — placing a photo window by
   typing "19,24,110,110" and finding out at print time is exactly the loop
   this replaces. Here you drag the box over the real artwork.

   English only, deliberately: the audience is the founder, not customers.
   The five-language rule is about the people buying books. */
import * as api from './api.js?v=20260825';

const TRIM_W = 148, TRIM_H = 210, SAFE = 5;   // the front panel, in mm

const S = {
  designs: [],
  editing: null,      // the design being edited, or null for a new one
  artworkFile: null,  // a File chosen but not yet uploaded
  artworkUrl: null,   // object URL for that file, so the preview is instant
  bookTypes: [],
  artSpec: null,
  dirty: false,
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
  }
  showScreen('main');
  await refresh();
}

function signOut() {
  api.setToken(null);
  S.designs = [];
  S.editing = null;
  showScreen('login');
  $('login-token').value = '';
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
  display_url: null,
};

function edit(design) {
  S.editing = design ? { ...design } : { ...BLANK };
  S.artworkFile = null;
  if (S.artworkUrl) { URL.revokeObjectURL(S.artworkUrl); S.artworkUrl = null; }
  S.dirty = false;
  $('edit-empty').classList.add('hidden');
  $('edit-form').classList.remove('hidden');
  $('f-artwork').value = '';
  $('art-note').classList.add('hidden');

  const d = S.editing;
  $('f-slug').value = d.slug || '';
  $('f-slug').disabled = false;
  $('f-name').value = d.name || '';
  for (const cb of $('f-types').querySelectorAll('input')) {
    cb.checked = (d.book_types || []).includes(cb.value);
  }
  $('f-has-photo').checked = !!d.photo_rect;
  const rect = d.photo_rect || { x_mm: 19, y_mm: 24, w_mm: 110, h_mm: 110 };
  $('f-rect-x').value = rect.x_mm;
  $('f-rect-y').value = rect.y_mm;
  $('f-rect-w').value = rect.w_mm;
  $('f-rect-h').value = rect.h_mm;
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
  $('edit-form').classList.add('hidden');
  $('edit-empty').classList.remove('hidden');
  renderList();
}

const markDirty = () => { S.dirty = true; };

function readRect() {
  if (!$('f-has-photo').checked) return null;
  return {
    x_mm: Number($('f-rect-x').value) || 0,
    y_mm: Number($('f-rect-y').value) || 0,
    w_mm: Math.max(1, Number($('f-rect-w').value) || 1),
    h_mm: Math.max(1, Number($('f-rect-h').value) || 1),
  };
}

function readTitle() {
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
  el.classList.remove('hidden');
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
      saved = await api.saveDesign(fields, S.artworkFile);
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
      });
    } else {
      return toast('Choose an artwork file for this new design.', 'warn');
    }
    toast(`Saved “${saved.name || saved.slug}”.`);
    await refresh();
    const fresh = S.designs.find((x) => x.design_id === saved.design_id);
    edit(fresh || saved);
  } catch (err) {
    if (err.status === 404 && !d.design_id) signOut();
    else toast(err.message || 'Could not save.', 'warn');
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
    toast(err.message || 'Could not retire.', 'warn');
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
  $('btn-new').addEventListener('click', () => edit(null));
  $('btn-cancel').addEventListener('click', closeEditor);
  $('btn-retire').addEventListener('click', retire);
  $('edit-form').addEventListener('submit', save);

  $('f-artwork').addEventListener('change', (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    S.artworkFile = file;
    if (S.artworkUrl) URL.revokeObjectURL(S.artworkUrl);
    S.artworkUrl = URL.createObjectURL(file);
    markDirty();
    // Warn about the aspect before upload, not after print.
    const probe = new Image();
    probe.onload = () => {
      const want = (S.artSpec ? S.artSpec.w_px / S.artSpec.h_px : 164 / 242);
      const got = probe.width / probe.height;
      const note = $('art-note');
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
    probe.src = S.artworkUrl;
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
