/* Editor application. Screens: start -> editor -> preview -> checkout -> order.
   All geometry mirrors the backend (backend/app/domain/geometry.py):
   trim 148x210mm, bleed 3mm (canvas 154x216), safe margin 5mm inside trim.
   Coordinates are millimetres with the origin at the trim top-left. */
import * as api from './api.js';
import { LANG_NAMES, applyStatic, fmtAmount, initLang, lang, setLang, t } from './i18n.js';
import { makeJobs, runJobs } from './upload.js';

const BLEED = 3, TRIM_W = 148, TRIM_H = 210, SAFE = 5;
const CANVAS_W = TRIM_W + 2 * BLEED, CANVAS_H = TRIM_H + 2 * BLEED;
const PT_MM = 25.4 / 72;
const FULL_BLEED = { x_mm: -BLEED, y_mm: -BLEED, w_mm: CANVAS_W, h_mm: CANVAS_H };
const INSET = { x_mm: 12, y_mm: 12, w_mm: TRIM_W - 24, h_mm: TRIM_H - 24 };
const ORDER_FLOW = ['pending_payment', 'paid', 'rendering', 'rendered',
                    'sent_to_production', 'shipped', 'delivered'];
const USABLE = new Set(['ready', 'duplicate']);
/* Editor approximations of the three print families (DejaVu Sans/Serif/Mono
   on the server) — the watermarked preview shows the real print fonts. */
const FONTS = {
  sans: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif",
  serif: "Georgia, 'Times New Roman', serif",
  mono: "'Courier New', Courier, monospace",
};
const fontKey = (name) => (FONTS[String(name || '').toLowerCase()]
  ? String(name).toLowerCase() : 'sans');
const fontStack = (name) => FONTS[fontKey(name)];

const S = {
  creds: null, book: null, photos: [], uploads: [],
  page: -1, sel: null, locked: false, dragging: false,
  dirty: false, saving: false, saveQueued: false, saveTimer: null,
  photoTimer: null, orderTimer: null, previewTimer: null,
  order: null,
};

const $ = (id) => document.getElementById(id);

/* ---------- small helpers ---------- */

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) el.setAttribute(k, v);
  }
  for (const c of children) {
    if (c !== null && c !== undefined) {
      el.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
  }
  return el;
}

function toast(msg, kind = 'info') {
  const el = h('div', { class: `toast ${kind}` }, msg);
  $('toasts').append(el);
  setTimeout(() => el.remove(), 4500);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function store(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch (e) { /* private mode */ }
}

function load(key) {
  try { return JSON.parse(localStorage.getItem(key)); } catch (e) { return null; }
}

function showScreen(name) {
  for (const s of document.querySelectorAll('.screen')) s.classList.remove('active');
  $(`screen-${name}`).classList.add('active');
  clearTimeout(S.orderTimer);
  clearTimeout(S.previewTimer);
}

function photoById(id) {
  return S.photos.find((p) => p.photo_id === id) || null;
}

function usableCount() {
  return S.photos.filter((p) => USABLE.has(p.status)).length;
}

function placedIds() {
  const ids = new Set();
  for (const page of S.book.layout.pages) {
    for (const pl of page.placements) ids.add(pl.photo_id);
  }
  return ids;
}

/* ---------- save engine ---------- */

function setSave(state) {
  const el = $('save-state');
  el.className = `save-state ${state}`;
  el.textContent = t(`save.${state}`);
}

function markDirty() {
  S.dirty = true;
  setSave('saving');
  clearTimeout(S.saveTimer);
  S.saveTimer = setTimeout(saveNow, 700);
}

async function saveNow() {
  if (S.saving) { S.saveQueued = true; return; }
  clearTimeout(S.saveTimer);
  if (!S.dirty) { setSave('saved'); return; }
  S.saving = true;
  S.dirty = false;
  const snapshot = JSON.parse(JSON.stringify(S.book.layout));
  try {
    const r = await api.patchLayout(S.creds, snapshot, S.book.layout_version);
    S.book.layout_version = r.layout_version;
    // Adopt the server's clamped document ONLY when nothing is mid-edit:
    // swapping the tree while a colour input, caret, or drag holds a
    // reference to the old objects would silently discard those edits.
    if (!S.dirty && !S.dragging && !canvasEditingFocus()) {
      S.book.layout = r.layout;
      renderCanvas();
      renderFilm();
    }
    setSave('saved');
  } catch (e) {
    await handleSaveError(e);
  }
  S.saving = false;
  if (S.saveQueued || S.dirty) { S.saveQueued = false; saveNow(); }
}

async function handleSaveError(e) {
  if (e.code === 'VERSION_CONFLICT') {
    await refetchBook();
    toast(t('err.synced'));
    setSave('saved');
  } else if (e.code === 'BOOK_LOCKED') {
    S.dirty = false;
    await refetchBook();
    toast(t('err.locked'));
  } else if (e.code === 'BOOK_EXPIRED' || e.status === 404) {
    handleGone();
  } else {
    S.dirty = true;
    setSave('error');
    S.saveTimer = setTimeout(saveNow, 3000);
  }
}

async function flushSave() {
  clearTimeout(S.saveTimer);
  for (let i = 0; i < 20 && (S.dirty || S.saving); i++) {
    if (!S.saving && S.dirty) await saveNow();
    else await sleep(150);
  }
  return !S.dirty;
}

function handleGone() {
  S.dirty = false;
  S.creds = null;
  store('mb-book', null);
  toast(t('err.expired'), 'warn');
  enterStart();
}

async function refetchBook() {
  const b = await api.getBook(S.creds);
  S.book = b;
  S.photos = b.photos || [];
  S.dirty = false;
  S.locked = b.status !== 'draft';
  renderAll();
}

/* ---------- start screen ---------- */

async function enterStart() {
  showScreen('start');
  const offline = !(await api.health());
  $('api-offline').classList.toggle('hidden', !offline);
  for (const b of document.querySelectorAll('.tier')) b.disabled = offline;
  const creds = load('mb-book');
  const card = $('resume-card');
  if (creds && !offline) {
    card.classList.remove('hidden');
    $('resume-info').textContent = '';
    api.getBook(creds).then((b) => {
      $('resume-info').textContent = t('start.resumeInfo', { pages: b.page_count });
    }).catch(() => {
      card.classList.add('hidden');
      store('mb-book', null);
    });
  } else {
    card.classList.add('hidden');
  }
}

async function startNewBook(tier) {
  try {
    const b = await api.createBook(tier);
    S.creds = { book_id: b.book_id, edit_token: b.edit_token };
    store('mb-book', S.creds);
    S.book = b;
    S.photos = [];
    S.uploads = [];
    S.page = -1;
    S.sel = null;
    S.locked = false;
    enterEditor();
  } catch (e) {
    toast(e.code === 'NETWORK' ? t('err.network') : t('err.generic'), 'warn');
  }
}

async function resumeBook() {
  S.creds = load('mb-book');
  if (!S.creds) return;
  try {
    await refetchBook();
    S.uploads = [];
    S.page = S.locked ? -1 : firstEmptyPage();
    S.sel = null;
    enterEditor();
  } catch (e) {
    if (e.code === 'BOOK_EXPIRED' || e.status === 404) handleGone();
    else toast(t('err.network'), 'warn');
  }
}

function firstEmptyPage() {
  const i = S.book.layout.pages.findIndex((p) => p.placements.length === 0);
  return i === -1 ? 0 : i;
}

/* ---------- editor screen ---------- */

function enterEditor() {
  showScreen('editor');
  $('tier-select').value = String(S.book.page_count);
  renderAll();
  schedulePhotoPoll();
}

function renderAll() {
  applyLocked();
  updatePageLabel();
  renderTray();
  renderCanvas();
  renderFilm();
  setSave(S.dirty || S.saving ? 'saving' : 'saved');
}

function applyLocked() {
  $('locked-banner').classList.toggle('hidden', !S.locked);
  $('btn-view-order').classList.toggle('hidden', !load('mb-order'));
  for (const id of ['tier-select', 'btn-autofill', 'btn-add-text', 'file-input']) {
    $(id).disabled = S.locked;
  }
  $('btn-preview').disabled = false;
  $('upload-zone').classList.toggle('disabled', S.locked);
}

function updatePageLabel() {
  $('page-label').textContent =
    S.page === -1 ? t('page.cover') : t('page.n', { n: S.page + 1 });
}

function updateEligibility() {
  const shortfall = S.book.page_count - usableCount();
  const el = $('elig-banner');
  el.classList.toggle('hidden', shortfall <= 0);
  if (shortfall > 0) el.textContent = t('elig.need', { n: shortfall });
}

/* ---------- tray ---------- */

function renderTray() {
  updateEligibility();
  $('tray-count').textContent =
    t('tray.count', { ready: usableCount(), need: S.book.page_count });
  const grid = $('tray-grid');
  grid.innerHTML = '';
  const placed = placedIds();
  const known = new Set(S.photos.map((p) => p.photo_id));

  for (const job of S.uploads) {
    if (job.photo_id && known.has(job.photo_id)) continue;   // server card exists
    const card = h('div', { class: `ph-card job ${job.status}` });
    if (job.status === 'failed') card.append(h('span', { class: 'badge err' }, t('tray.failed')));
    else card.append(h('span', { class: 'spin' }), h('span', { class: 'badge' }, t('tray.processing')));
    card.append(h('span', { class: 'ph-name' }, job.name));
    grid.append(card);
  }

  for (const p of S.photos) {
    const card = h('div', {
      class: 'ph-card' + (USABLE.has(p.status) ? '' : ' pending'),
      draggable: USABLE.has(p.status) && !S.locked ? 'true' : null,
      ondragstart: (e) => e.dataTransfer.setData('text/mb-photo', p.photo_id),
      onclick: () => { if (USABLE.has(p.status) && !S.locked) placePhoto(p); },
    });
    if (p.thumb_url) {
      card.append(h('img', { src: p.thumb_url, alt: '', loading: 'lazy' }));
    }
    if (p.status === 'pending' || p.status === 'processing') {
      card.append(h('span', { class: 'spin' }));
    } else if (p.status === 'failed') {
      card.append(h('span', { class: 'badge err' }, t('tray.failed')));
    } else {
      if (p.status === 'duplicate') card.append(h('span', { class: 'badge' }, t('tray.duplicate')));
      if (p.resolution_status && p.resolution_status !== 'ok') {
        card.append(h('span', { class: 'badge warn' }, t('tray.lowres')));
      }
      if (placed.has(p.photo_id)) card.append(h('span', { class: 'badge ok' }, '✓'));
    }
    if (!S.locked) {
      card.append(h('button', {
        class: 'ph-del', 'aria-label': t('tool.remove'),
        onclick: (e) => { e.stopPropagation(); removePhoto(p); },
      }, '×'));
    }
    grid.append(card);
  }
}

async function removePhoto(p) {
  if (!confirm(t('confirm.deletePhoto'))) return;
  try {
    await api.deletePhoto(S.creds, p.photo_id);
  } catch (e) {
    toast(t('err.generic'), 'warn');
    return;
  }
  S.photos = S.photos.filter((x) => x.photo_id !== p.photo_id);
  let touched = false;
  for (const page of S.book.layout.pages) {
    const before = page.placements.length;
    page.placements = page.placements.filter((pl) => pl.photo_id !== p.photo_id);
    touched = touched || page.placements.length !== before;
  }
  if (S.book.layout.cover.photo_id === p.photo_id) {
    S.book.layout.cover.photo_id = null;
    touched = true;
  }
  if (touched) markDirty();
  renderAll();
}

function schedulePhotoPoll() {
  if (S.photoTimer) return;
  S.photoTimer = setTimeout(pollPhotos, 1500);
}

async function pollPhotos() {
  S.photoTimer = null;
  if (!S.creds) return;
  try {
    const r = await api.listPhotos(S.creds);
    S.photos = r.photos;
    if ($('screen-editor').classList.contains('active')) {
      renderTray();
      renderFilm();
      renderCanvas();
    }
  } catch (e) { /* transient; next poll retries */ }
  const busy = S.photos.some((p) => p.status === 'pending' || p.status === 'processing')
    || S.uploads.some((j) => j.status === 'queued' || j.status === 'uploading');
  if (busy) schedulePhotoPoll();
}

function startUploads(files) {
  if (S.locked || !files || !files.length) return;
  const jobs = makeJobs([...files]);
  S.uploads.push(...jobs);
  renderTray();
  runJobs(jobs, S.creds, () => { renderTray(); schedulePhotoPoll(); })
    .then(() => schedulePhotoPoll());
  schedulePhotoPoll();
}

/* ---------- placing ---------- */

function placePhoto(p) {
  if (S.page === -1) {
    S.book.layout.cover.photo_id = p.photo_id;
    markDirty();
    renderCanvas();
    renderTray();
    return;
  }
  placeOnPage(p.photo_id, S.page, true);
}

function placeOnPage(photoId, index, advance) {
  const page = S.book.layout.pages[index];
  const wasEmpty = page.placements.length === 0;
  page.placements = [{ photo_id: photoId, ...FULL_BLEED, rotation: 0, fit: 'cover' }];
  markDirty();
  if (advance && wasEmpty) {
    const next = S.book.layout.pages.findIndex(
      (pg, i) => i > index && pg.placements.length === 0);
    if (next !== -1) S.page = next;
  }
  S.sel = null;
  updatePageLabel();
  renderCanvas();
  renderFilm();
  renderTray();
}

/* ---------- canvas ---------- */

const pct = (mm, total) => `${((mm) / total) * 100}%`;

function canvasScale() {   // px per mm
  return $('page-canvas').clientWidth / CANVAS_W;
}

/* Pointer event -> trim-origin mm coordinates on the page canvas. */
function evToMM(e) {
  const r = $('page-canvas').getBoundingClientRect();
  const s = r.width / CANVAS_W;
  return { x: (e.clientX - r.left) / s - BLEED, y: (e.clientY - r.top) / s - BLEED };
}

function focusSelText() {
  // Synchronous: the box exists as soon as renderCanvas returns, and typing
  // may start immediately after the tap that created it.
  const el = document.querySelector('.textbox.sel .textbox-content');
  if (!el) return;
  el.focus();
  const range = document.createRange();
  range.selectNodeContents(el);
  range.collapse(false);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
}

function canvasEditingFocus() {
  const a = document.activeElement;
  if (!a) return false;
  // Canvas text/caret, colour tools, and the selection toolbar all hold live
  // references into the layout tree — don't rebuild under them.
  return ['page-canvas', 'page-tools', 'sel-toolbar']
    .some((id) => $(id).contains(a));
}

function renderCanvas(force) {
  if (!force && canvasEditingFocus()) return;   // don't yank the caret mid-typing
  const canvas = $('page-canvas');
  canvas.innerHTML = '';
  updatePageLabel();
  if (S.page === -1) renderCover(canvas);
  else renderPage(canvas);
  renderPageTools();
  renderSelToolbar();
}

/* Always-available colour controls for the current page / the cover. */
function renderPageTools() {
  const box = $('page-tools');
  box.innerHTML = '';
  if (S.locked) return;
  const colorInput = (value, label, oninput, onchange) => {
    const input = h('input', { type: 'color', value, title: label, 'aria-label': label });
    input.addEventListener('input', () => oninput(input.value));
    if (onchange) input.addEventListener('change', () => onchange(input.value));
    return h('label', { class: 'color-tool', title: label },
             input, h('span', {}, label));
  };
  if (S.page === -1) {
    const cover = S.book.layout.cover;
    box.append(colorInput(cover.bg_color || '#ffffff', t('tool.coverColor'), (v) => {
      cover.bg_color = v;
      $('page-canvas').style.background = v;
      markDirty();
    }, () => renderCanvas()));
    box.append(colorInput(cover.title_color || (cover.photo_id ? '#ffffff' : '#1a1a1a'),
                          t('tool.titleColor'), (v) => {
      cover.title_color = v;
      for (const inp of document.querySelectorAll('.cover-titles input')) {
        inp.style.color = v;
      }
      markDirty();
    }));
  } else {
    const page = S.book.layout.pages[S.page];
    box.append(colorInput(page.bg_color || '#ffffff', t('tool.pageColor'), (v) => {
      page.bg_color = v;
      $('page-canvas').style.background = v;
      markDirty();
    }, () => renderFilm()));
  }
}

function renderCover(canvas) {
  canvas.className = 'page-canvas cover-mode';
  const cover = S.book.layout.cover;
  canvas.style.background = cover.bg_color || '#eceff4';
  const photo = cover.photo_id ? photoById(cover.photo_id) : null;
  if (photo && photo.display_url) {
    canvas.append(h('img', {
      class: 'cover-img', src: photo.display_url, alt: '',
      onclick: (e) => { e.stopPropagation(); select({ kind: 'cover' }); },
    }));
  } else {
    canvas.append(h('div', { class: 'canvas-empty' }, t('canvas.empty')));
  }
  const scale = canvas.clientWidth / CANVAS_W;   // px per mm
  const textColor = cover.title_color || (photo ? '#ffffff' : '#1a1a1a');
  const titles = h('div', { class: 'cover-titles' });
  const title = h('input', {
    class: 'cover-title', value: cover.title, maxlength: '200',
    placeholder: t('cover.titlePh'),
  });
  title.style.fontSize = `${cover.title_size_pt * PT_MM * scale}px`;
  title.style.fontFamily = fontStack(cover.title_font);
  title.style.color = textColor;
  title.addEventListener('input', () => {
    cover.title = title.value;
    markDirty();
  });
  const subtitle = h('input', {
    class: 'cover-subtitle', value: cover.subtitle, maxlength: '200',
    placeholder: t('cover.subtitlePh'),
  });
  subtitle.style.fontSize = `${0.5 * cover.title_size_pt * PT_MM * scale}px`;
  subtitle.style.fontFamily = fontStack(cover.title_font);
  subtitle.style.color = textColor;
  subtitle.addEventListener('input', () => {
    cover.subtitle = subtitle.value;
    markDirty();
  });
  titles.append(title, subtitle);
  canvas.append(titles);
}

function renderPage(canvas) {
  canvas.className = 'page-canvas page-mode';
  const page = S.book.layout.pages[S.page];
  canvas.style.background = page.bg_color || '#ffffff';

  canvas.append(
    h('div', {
      class: 'guide trim',
      style: `inset:${(BLEED / CANVAS_H) * 100}% ${(BLEED / CANVAS_W) * 100}%`,
    }),
    h('div', {
      class: 'guide safe',
      style: `inset:${((BLEED + SAFE) / CANVAS_H) * 100}% ${((BLEED + SAFE) / CANVAS_W) * 100}%`,
    }),
  );

  const pl = page.placements[0];
  if (pl) {
    canvas.append(makePlacement(pl));
  } else {
    canvas.append(h('div', { class: 'canvas-empty' }, t('canvas.empty')));
  }

  const scale = canvas.clientWidth / CANVAS_W;   // px per mm
  for (const tb of page.texts) {
    canvas.append(makeTextBox(tb, scale));
  }
}

function placeRect(el, r) {
  el.style.left = pct(r.x_mm + BLEED, CANVAS_W);
  el.style.top = pct(r.y_mm + BLEED, CANVAS_H);
  el.style.width = pct(r.w_mm, CANVAS_W);
  el.style.height = pct(r.h_mm, CANVAS_H);
}

function makePlacement(pl) {
  const photo = photoById(pl.photo_id);
  const box = h('div', {
    class: 'placement' + (isSel('placement', 0) ? ' sel' : ''),
  });
  placeRect(box, pl);
  if (photo && photo.display_url) {
    box.append(h('img', {
      src: photo.display_url, alt: '', style: `object-fit:${pl.fit}`, draggable: 'false',
    }));
  } else {
    box.append(h('span', { class: 'spin' }));
  }

  // Drag to move; a still tap/click just selects.
  box.addEventListener('pointerdown', (e) => {
    if (S.locked || e.target.classList.contains('rs')) return;
    e.preventDefault();
    e.stopPropagation();
    const scale = canvasScale();
    const sx = e.clientX, sy = e.clientY, ox = pl.x_mm, oy = pl.y_mm;
    let moved = false;
    S.dragging = true;
    const move = (ev) => {
      if (!moved && Math.hypot(ev.clientX - sx, ev.clientY - sy) < 4) return;
      if (!moved) { moved = true; select({ kind: 'placement', idx: 0 }, true); box.classList.add('sel'); }
      pl.x_mm = clamp(ox + (ev.clientX - sx) / scale,
                      -BLEED, Math.max(-BLEED, CANVAS_W - BLEED - pl.w_mm));
      pl.y_mm = clamp(oy + (ev.clientY - sy) / scale,
                      -BLEED, Math.max(-BLEED, CANVAS_H - BLEED - pl.h_mm));
      placeRect(box, pl);
    };
    const up = () => {
      S.dragging = false;
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      if (moved) markDirty();
      // A still tap selects — unless something (e.g. type-anywhere on this
      // same tap) already re-rendered and replaced this element.
      else if (box.isConnected) select({ kind: 'placement', idx: 0 });
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });

  if (isSel('placement', 0) && !S.locked) {
    for (const corner of ['nw', 'ne', 'sw', 'se']) {
      const handle = h('div', { class: `rs ${corner}` });
      handle.addEventListener('pointerdown',
        (e) => startPlacementResize(e, box, pl, corner));
      box.append(handle);
    }
  }
  return box;
}

function startPlacementResize(e, box, pl, corner) {
  e.preventDefault();
  e.stopPropagation();
  const scale = canvasScale();
  const sx = e.clientX, sy = e.clientY;
  const o = { x: pl.x_mm, y: pl.y_mm, w: pl.w_mm, h: pl.h_mm };
  const MIN = 20;
  S.dragging = true;
  const move = (ev) => {
    const dx = (ev.clientX - sx) / scale, dy = (ev.clientY - sy) / scale;
    let { x, y, w, h } = { x: o.x, y: o.y, w: o.w, h: o.h };
    if (corner.includes('e')) w = o.w + dx;
    if (corner.includes('s')) h = o.h + dy;
    if (corner.includes('w')) w = o.w - dx;
    if (corner.includes('n')) h = o.h - dy;
    w = clamp(w, MIN, CANVAS_W);
    h = clamp(h, MIN, CANVAS_H);
    if (corner.includes('w')) x = o.x + (o.w - w);
    if (corner.includes('n')) y = o.y + (o.h - h);
    x = clamp(x, -BLEED, CANVAS_W - BLEED - w);
    y = clamp(y, -BLEED, CANVAS_H - BLEED - h);
    Object.assign(pl, { x_mm: x, y_mm: y, w_mm: w, h_mm: h });
    placeRect(box, pl);
  };
  const up = () => {
    S.dragging = false;
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    markDirty();
    renderSelToolbar();
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
}

function makeTextBox(tb, scale) {
  const box = h('div', {
    class: 'textbox' + (isSel('text', tb.id) ? ' sel' : ''),
    'data-id': tb.id,
    style: `left:${pct(tb.x_mm + BLEED, CANVAS_W)};top:${pct(tb.y_mm + BLEED, CANVAS_H)};` +
           `width:${pct(tb.w_mm, CANVAS_W)};min-height:${pct(tb.h_mm, CANVAS_H)};` +
           `font-size:${tb.size_pt * PT_MM * scale}px;text-align:${tb.align};color:${tb.color};` +
           `font-family:${fontStack(tb.font)}`,
  });
  const content = h('div', {
    class: 'textbox-content',
    contenteditable: S.locked ? 'false' : 'true',
    'data-ph': t('tool.addText').replace('+ ', ''),
  }, tb.content);
  content.addEventListener('input', () => {
    tb.content = content.innerText.slice(0, 1000);
    markDirty();
  });
  content.addEventListener('focus', () => select({ kind: 'text', id: tb.id }, true));

  // Drag anywhere on the box to move it; a still click starts editing.
  // While the caret is inside, pointer events do native text selection and
  // the ⠿ handle moves the box instead.
  box.addEventListener('pointerdown', (e) => {
    if (S.locked) return;
    if (document.activeElement === content) return;
    if (e.target.closest('.tb-handle, .tb-resize')) return;
    e.preventDefault();
    e.stopPropagation();
    const moved = startTextDrag(e, box, tb);
    moved.then((didMove) => {
      if (!didMove) {
        S.sel = { kind: 'text', id: tb.id };
        renderCanvas(true);
        focusSelText();
      }
    });
  });

  const handle = h('div', { class: 'tb-handle' }, '⠿');
  handle.addEventListener('pointerdown', (e) => {
    if (S.locked) return;
    e.preventDefault();
    e.stopPropagation();
    startTextDrag(e, box, tb);
  });

  const resize = h('div', { class: 'tb-resize' });
  resize.addEventListener('pointerdown', (e) => {
    if (S.locked) return;
    e.preventDefault();
    e.stopPropagation();
    const scale2 = canvasScale();
    const sx = e.clientX, ow = tb.w_mm;
    S.dragging = true;
    const move = (ev) => {
      tb.w_mm = clamp(ow + (ev.clientX - sx) / scale2, 20, TRIM_W - SAFE - tb.x_mm);
      box.style.width = pct(tb.w_mm, CANVAS_W);
    };
    const up = () => {
      S.dragging = false;
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      markDirty();
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });

  box.append(handle, content, resize);
  return box;
}

/* Shared text-box move logic; resolves to true if the pointer actually
   dragged (vs a still click). */
function startTextDrag(e, box, tb) {
  return new Promise((resolve) => {
    const scale = canvasScale();
    const sx = e.clientX, sy = e.clientY, ox = tb.x_mm, oy = tb.y_mm;
    let moved = false;
    S.dragging = true;
    const move = (ev) => {
      if (!moved && Math.hypot(ev.clientX - sx, ev.clientY - sy) < 4) return;
      if (!moved) {
        moved = true;
        S.sel = { kind: 'text', id: tb.id };
        highlightSel();
        box.classList.add('sel');
        renderSelToolbar();
      }
      tb.x_mm = clamp(ox + (ev.clientX - sx) / scale,
                      SAFE, Math.max(SAFE, TRIM_W - SAFE - tb.w_mm));
      tb.y_mm = clamp(oy + (ev.clientY - sy) / scale,
                      SAFE, Math.max(SAFE, TRIM_H - SAFE - tb.h_mm));
      box.style.left = pct(tb.x_mm + BLEED, CANVAS_W);
      box.style.top = pct(tb.y_mm + BLEED, CANVAS_H);
    };
    const up = () => {
      S.dragging = false;
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      if (moved) markDirty();
      resolve(moved);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });
}

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

function isSel(kind, key) {
  if (!S.sel || S.sel.kind !== kind) return false;
  return kind === 'placement' ? S.sel.idx === key : S.sel.id === key;
}

function select(sel, keepFocus) {
  S.sel = sel;
  if (keepFocus) { renderSelToolbar(); highlightSel(); return; }
  renderCanvas(true);
}

function highlightSel() {
  for (const el of document.querySelectorAll('.textbox, .placement')) {
    el.classList.remove('sel');
  }
  if (!S.sel) return;
  const el = S.sel.kind === 'placement'
    ? document.querySelector('.placement')
    : document.querySelector(`.textbox[data-id="${S.sel.id}"]`);
  if (el) el.classList.add('sel');
}

/* ---------- selection toolbar ---------- */

function renderSelToolbar() {
  const bar = $('sel-toolbar');
  bar.innerHTML = '';
  if (!S.sel || S.locked) { bar.classList.add('hidden'); return; }
  bar.classList.remove('hidden');

  if (S.sel.kind === 'placement') {
    const page = S.book.layout.pages[S.page];
    const pl = page.placements[0];
    if (!pl) { bar.classList.add('hidden'); return; }
    const isFull = pl.x_mm === FULL_BLEED.x_mm && pl.w_mm === FULL_BLEED.w_mm;
    bar.append(
      h('button', {
        class: 'btn small' + (isFull ? ' active' : ''),
        onclick: () => { Object.assign(pl, FULL_BLEED); markDirty(); renderCanvas(true); },
      }, t('tool.fullPage')),
      h('button', {
        class: 'btn small' + (!isFull ? ' active' : ''),
        onclick: () => { Object.assign(pl, INSET); markDirty(); renderCanvas(true); },
      }, t('tool.inset')),
      h('button', {
        class: 'btn small',
        onclick: () => {
          pl.fit = pl.fit === 'cover' ? 'contain' : 'cover';
          markDirty();
          renderCanvas(true);
        },
      }, pl.fit === 'cover' ? t('tool.fitContain') : t('tool.fitCover')),
      h('button', {
        class: 'btn small danger',
        onclick: () => {
          page.placements = [];
          S.sel = null;
          markDirty();
          renderCanvas(true);
          renderFilm();
          renderTray();
        },
      }, t('tool.remove')),
    );
  } else if (S.sel.kind === 'text') {
    const page = S.book.layout.pages[S.page];
    const tb = page.texts.find((x) => x.id === S.sel.id);
    if (!tb) { bar.classList.add('hidden'); return; }
    const fontSel = h('select', { 'aria-label': 'Font' });
    for (const f of ['sans', 'serif', 'mono']) {
      fontSel.append(h('option', {
        value: f, selected: fontKey(tb.font) === f ? '' : null,
        style: `font-family:${FONTS[f]}`,
      }, f));
    }
    fontSel.addEventListener('change', () => {
      tb.font = fontSel.value;
      markDirty();
      renderCanvas(true);
    });
    const size = h('select', { 'aria-label': 'Size' });
    for (const v of [9, 11, 14, 18, 24, 32]) {
      size.append(h('option', { value: v, selected: tb.size_pt === v ? '' : null }, `${v} pt`));
    }
    size.addEventListener('change', () => {
      tb.size_pt = Number(size.value);
      markDirty();
      renderCanvas(true);
    });
    const color = h('input', { type: 'color', value: tb.color, 'aria-label': 'Color' });
    color.addEventListener('input', () => {
      tb.color = color.value;
      markDirty();
      renderCanvas(true);
    });
    bar.append(fontSel, size);
    for (const [al, label] of [['left', '⇤'], ['center', '↔'], ['right', '⇥']]) {
      bar.append(h('button', {
        class: 'btn small' + (tb.align === al ? ' active' : ''),
        onclick: () => { tb.align = al; markDirty(); renderCanvas(true); },
      }, label));
    }
    bar.append(color, h('button', {
      class: 'btn small danger',
      onclick: () => {
        page.texts = page.texts.filter((x) => x.id !== tb.id);
        S.sel = null;
        markDirty();
        renderCanvas(true);
      },
    }, t('tool.remove')));
  } else if (S.sel.kind === 'cover') {
    const cover = S.book.layout.cover;
    const fontSel = h('select', { 'aria-label': 'Font' });
    for (const f of ['sans', 'serif', 'mono']) {
      fontSel.append(h('option', {
        value: f, selected: fontKey(cover.title_font) === f ? '' : null,
        style: `font-family:${FONTS[f]}`,
      }, f));
    }
    fontSel.addEventListener('change', () => {
      cover.title_font = fontSel.value;
      markDirty();
      renderCanvas(true);
    });
    const size = h('select', { 'aria-label': t('tool.titleSize') });
    for (const v of [20, 28, 36]) {
      size.append(h('option', { value: v, selected: cover.title_size_pt === v ? '' : null }, `${v} pt`));
    }
    size.addEventListener('change', () => {
      cover.title_size_pt = Number(size.value);
      markDirty();
      renderCanvas(true);
    });
    bar.append(fontSel, size, h('button', {
      class: 'btn small danger',
      onclick: () => {
        cover.photo_id = null;
        S.sel = null;
        markDirty();
        renderCanvas(true);
        renderFilm();
      },
    }, t('tool.remove')));
  }
}

function addTextBox() {
  addTextBoxAt(TRIM_W / 2, 177);   // classic caption spot near the bottom
}

/* "Type anywhere": create a text box centred on a point (trim mm), focused. */
function addTextBoxAt(cx, cy) {
  if (S.page === -1 || S.locked) return;
  const page = S.book.layout.pages[S.page];
  if (page.texts.length >= 20) return;
  const w = 70, hgt = 14;
  const tb = {
    id: `t${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`,
    x_mm: clamp(cx - w / 2, SAFE, TRIM_W - SAFE - w),
    y_mm: clamp(cy - hgt / 2, SAFE, TRIM_H - SAFE - hgt),
    w_mm: w, h_mm: hgt,
    content: '', font: 'sans', size_pt: 14, align: 'center', color: '#1a1a1a',
  };
  page.texts.push(tb);
  S.sel = { kind: 'text', id: tb.id };
  markDirty();
  renderCanvas(true);
  focusSelText();
}

/* ---------- filmstrip ---------- */

function renderFilm() {
  const nav = $('filmstrip');
  nav.innerHTML = '';
  const coverPhoto = S.book.layout.cover.photo_id
    ? photoById(S.book.layout.cover.photo_id) : null;
  nav.append(filmItem(-1, coverPhoto, t('page.cover')));
  S.book.layout.pages.forEach((page, i) => {
    const pl = page.placements[0];
    const photo = pl ? photoById(pl.photo_id) : null;
    nav.append(filmItem(i, photo, String(i + 1), !pl));
  });
  const active = nav.querySelector('.film-item.active');
  if (active) active.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}

function filmItem(index, photo, label, empty) {
  const bg = index === -1
    ? (S.book.layout.cover.bg_color || '#ffffff')
    : (S.book.layout.pages[index].bg_color || '#ffffff');
  const item = h('button', {
    class: 'film-item' + (S.page === index ? ' active' : '') + (empty ? ' empty' : ''),
    onclick: () => { S.page = index; S.sel = null; renderCanvas(true); renderFilm(); },
    ondragover: (e) => { if (index >= 0) e.preventDefault(); },
    ondrop: (e) => {
      e.preventDefault();
      const id = e.dataTransfer.getData('text/mb-photo');
      if (id && index >= 0 && !S.locked) {
        S.page = index;
        placeOnPage(id, index, false);
      }
    },
  });
  const thumb = h('div', { class: 'film-thumb' });
  thumb.style.background = bg;
  if (photo && photo.thumb_url) thumb.append(h('img', { src: photo.thumb_url, alt: '' }));
  item.append(thumb, h('span', { class: 'film-label' }, label));
  return item;
}

/* ---------- header actions ---------- */

async function changeTier(next) {
  const cur = S.book.page_count;
  if (next === cur) return;
  if (next < cur) {
    const trailing = S.book.layout.pages.slice(next);
    const hasContent = trailing.some((p) => p.placements.length || p.texts.length);
    if (hasContent && !confirm(t('confirm.shrink'))) {
      $('tier-select').value = String(cur);
      return;
    }
  }
  if (!(await flushSave())) { $('tier-select').value = String(cur); return; }
  try {
    const r = await api.patchPageCount(S.creds, next, S.book.layout_version);
    S.book.page_count = r.page_count;
    S.book.layout = r.layout;
    S.book.layout_version = r.layout_version;
    if (S.page >= r.page_count) S.page = r.page_count - 1;
    for (const w of r.warnings || []) toast(w, 'warn');
    renderAll();
  } catch (e) {
    $('tier-select').value = String(cur);
    await handleActionError(e);
  }
}

async function autoFill() {
  if (!(await flushSave())) return;
  try {
    const r = await api.autoPlace(S.creds, S.book.layout_version);
    S.book.layout = r.layout;
    S.book.layout_version = r.layout_version;
    S.sel = null;
    toast(t('autofill.done', {
      placed: r.placed_count, left: (r.unplaced_photo_ids || []).length,
    }));
    renderAll();
  } catch (e) {
    await handleActionError(e);
  }
}

async function handleActionError(e) {
  if (e.code === 'VERSION_CONFLICT') { await refetchBook(); toast(t('err.synced')); }
  else if (e.code === 'BOOK_LOCKED') { await refetchBook(); toast(t('err.locked'), 'warn'); }
  else if (e.code === 'BOOK_EXPIRED' || e.status === 404) handleGone();
  else if (e.code === 'NETWORK') toast(t('err.network'), 'warn');
  else toast(e.message || t('err.generic'), 'warn');
}

/* ---------- preview ---------- */

async function openPreview() {
  showScreen('preview');
  $('pv-grid').innerHTML = '';
  $('pv-stale').classList.add('hidden');
  $('pv-confirm').checked = false;
  $('pv-checkout').disabled = true;
  $('pv-status').textContent = t('preview.rendering');
  $('pv-status').classList.add('busy');
  await flushSave();
  try {
    if (!S.locked) await api.requestPreview(S.creds);
    pollPreview();
  } catch (e) {
    $('pv-status').classList.remove('busy');
    if (e.code === 'BOOK_LOCKED') pollPreview();
    else { $('pv-status').textContent = t('preview.failed'); await handleActionError(e); }
  }
}

async function pollPreview() {
  let r;
  try {
    r = await api.getPreview(S.creds);
  } catch (e) {
    $('pv-status').classList.remove('busy');
    $('pv-status').textContent = t('preview.failed');
    return;
  }
  if (r.status === 'ready') {
    $('pv-status').textContent = '';
    $('pv-status').classList.remove('busy');
    $('pv-stale').classList.toggle('hidden', !r.stale);
    const grid = $('pv-grid');
    grid.innerHTML = '';
    r.page_urls.forEach((url, i) => {
      grid.append(h('figure', { class: 'pv-page' },
        h('img', { src: url, alt: `Page ${i + 1}`, loading: 'lazy' }),
        h('figcaption', {}, String(i + 1))));
    });
  } else if (r.status === 'failed') {
    $('pv-status').classList.remove('busy');
    $('pv-status').textContent = t('preview.failed');
  } else {
    S.previewTimer = setTimeout(pollPreview, 1500);
  }
}

/* ---------- checkout & order ---------- */

async function submitCheckout(e) {
  e.preventDefault();
  const form = $('co-form');
  const btn = form.querySelector('button[type=submit]');
  btn.disabled = true;
  const data = Object.fromEntries(new FormData(form).entries());
  const body = {
    name: data.name.trim(), phone: data.phone.trim(), address: data.address.trim(),
    confirmed_preview: true,
  };
  if (data.email && data.email.trim()) body.email = data.email.trim();
  try {
    const r = await api.checkout(S.creds, body);
    S.order = {
      ref: r.human_ref, phone: body.phone, amount_minor: r.amount_minor,
      currency: r.currency, status: r.order_status, payment: r.payment,
    };
    store('mb-order', S.order);
    S.locked = true;
    showOrder();
  } catch (err) {
    if (err.code === 'PREVIEW_STALE' || err.code === 'PREVIEW_NOT_CONFIRMED') {
      toast(t('preview.stale'), 'warn');
      openPreview();
    } else if (err.code === 'PHOTOS_INSUFFICIENT' || err.code === 'PAGES_INCOMPLETE') {
      toast(err.message || t('err.generic'), 'warn');
      enterEditor();
    } else if (err.code === 'BOOK_LOCKED') {
      const saved = load('mb-order');
      if (saved) { S.order = saved; showOrder(); } else toast(t('err.locked'), 'warn');
    } else {
      await handleActionError(err);
    }
  } finally {
    btn.disabled = false;
  }
}

function showOrder() {
  showScreen('order');
  $('or-lookup').classList.add('hidden');
  $('or-details').classList.remove('hidden');
  $('or-ref').textContent = S.order.ref;
  $('or-amount').textContent = fmtAmount(S.order.amount_minor);
  const dev = (S.order.payment && S.order.payment.providers_available) || [];
  const pending = S.order.status === 'pending_payment';
  $('or-dev').classList.toggle('hidden', !(pending && dev.includes('dev')));
  $('or-pay-note').classList.toggle('hidden', !pending);
  renderTimeline(S.order.status);
  pollOrder();
}

function renderTimeline(status) {
  const ol = $('or-timeline');
  ol.innerHTML = '';
  if (status === 'cancelled') {
    ol.append(h('li', { class: 'now warn' }, t('st.cancelled')));
    return;
  }
  const shown = status === 'render_failed' ? 'rendering' : status;
  const reached = ORDER_FLOW.indexOf(shown);
  ORDER_FLOW.forEach((st, i) => {
    const cls = i < reached ? 'done' : i === reached ? 'now' : '';
    ol.append(h('li', { class: cls }, t(`st.${st}`)));
  });
}

async function pollOrder() {
  clearTimeout(S.orderTimer);
  if (!S.order || !$('screen-order').classList.contains('active')) return;
  try {
    const r = await api.orderStatus(S.order.ref, S.order.phone);
    if (r.status !== S.order.status) {
      S.order.status = r.status;
      store('mb-order', S.order);
      renderTimeline(r.status);
      const pending = r.status === 'pending_payment';
      $('or-dev').classList.toggle('hidden',
        !(pending && ((S.order.payment && S.order.payment.providers_available) || []).includes('dev')));
      $('or-pay-note').classList.toggle('hidden', !pending);
    }
  } catch (e) { /* transient */ }
  if (!['delivered', 'cancelled'].includes(S.order.status)) {
    S.orderTimer = setTimeout(pollOrder, 3000);
  }
}

async function devPayNow() {
  const secret = (window.MEMOBOOK && window.MEMOBOOK.devPaymentSecret)
    || prompt(t('order.devHint'));
  if (!secret) return;
  const btn = $('or-dev-pay');
  btn.disabled = true;
  try {
    await api.devPay(S.order.ref, S.order.amount_minor, secret);
    await pollOrder();
  } catch (e) {
    toast(e.message || t('err.generic'), 'warn');
  } finally {
    btn.disabled = false;
  }
}

function showOrderLookup() {
  S.order = null;
  showScreen('order');
  $('or-details').classList.add('hidden');
  $('or-lookup').classList.remove('hidden');
}

async function submitLookup(e) {
  e.preventDefault();
  const data = Object.fromEntries(new FormData($('or-lookup')).entries());
  try {
    const r = await api.orderStatus(data.ref.trim().toUpperCase(), data.phone.trim());
    S.order = {
      ref: r.human_ref, phone: data.phone.trim(), amount_minor: r.amount_minor,
      currency: r.currency, status: r.status, payment: null,
    };
    store('mb-order', S.order);
    showOrder();
  } catch (err) {
    toast(err.code === 'ORDER_NOT_FOUND' ? t('order.notFound')
      : err.code === 'NETWORK' ? t('err.network') : t('err.generic'), 'warn');
  }
}

/* ---------- wiring ---------- */

function buildLangSelect() {
  const sel = $('lang-select');
  sel.innerHTML = '';
  for (const [code, name] of Object.entries(LANG_NAMES)) {
    sel.append(h('option', { value: code, selected: code === lang ? '' : null }, name));
  }
  sel.addEventListener('change', () => {
    setLang(sel.value);
    if (S.book) renderAll();
  });
}

function bind() {
  $('tier-grid').addEventListener('click', (e) => {
    const b = e.target.closest('.tier');
    if (b && !b.disabled) startNewBook(Number(b.dataset.tier));
  });
  $('btn-resume').addEventListener('click', resumeBook);
  $('btn-new').addEventListener('click', () => {
    if (confirm(t('confirm.newBook'))) {
      store('mb-book', null);
      $('resume-card').classList.add('hidden');
    }
  });
  $('track-link').addEventListener('click', (e) => { e.preventDefault(); showOrderLookup(); });

  $('ed-back').addEventListener('click', async () => { await flushSave(); enterStart(); });
  $('file-input').addEventListener('change', (e) => {
    startUploads(e.target.files);
    e.target.value = '';
  });
  const zone = $('upload-zone');
  zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('over'));
  zone.addEventListener('drop', (e) => {
    e.preventDefault();
    zone.classList.remove('over');
    startUploads(e.dataTransfer.files);
  });
  $('btn-add-text').addEventListener('click', addTextBox);
  $('btn-autofill').addEventListener('click', autoFill);
  $('btn-preview').addEventListener('click', openPreview);
  $('tier-select').addEventListener('change', (e) => changeTier(Number(e.target.value)));
  $('btn-view-order').addEventListener('click', () => {
    const saved = load('mb-order');
    if (saved) { S.order = saved; showOrder(); }
  });
  const canvasWrap = $('canvas-wrap');
  canvasWrap.addEventListener('click', (e) => {
    if (e.target.closest('.placement, .textbox, .cover-img, .rs, .tb-handle, .tb-resize')) {
      return;   // interactions on elements manage selection themselves
    }
    // The canvas re-rendered during this gesture (e.g. type-anywhere just
    // created a box) — this click's target is gone; don't undo the selection.
    if (!e.target.isConnected) return;
    if (canvasEditingFocus()) return;   // caret just landed in a text box
    if (S.sel) { S.sel = null; renderCanvas(true); }
  });
  // "Type anywhere": double-click / double-tap adds a text box at that point.
  // Hand-rolled detection — selection re-renders the canvas DOM between the
  // two clicks, which breaks native dblclick, and mobile double-tap needs it.
  const lastTap = { t: 0, x: 0, y: 0 };
  $('page-canvas').addEventListener('pointerup', (e) => {
    if (S.locked || S.page === -1) return;
    if (e.target.closest('.textbox, .rs, .tb-handle, .tb-resize')) { lastTap.t = 0; return; }
    const now = performance.now();
    const isDouble = now - lastTap.t < 400
      && Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) < 8;
    lastTap.t = now;
    lastTap.x = e.clientX;
    lastTap.y = e.clientY;
    if (isDouble) {
      lastTap.t = 0;
      const p = evToMM(e);
      addTextBoxAt(p.x, p.y);
    }
  });
  canvasWrap.addEventListener('dragover', (e) => e.preventDefault());
  canvasWrap.addEventListener('drop', (e) => {
    e.preventDefault();
    const id = e.dataTransfer.getData('text/mb-photo');
    if (id && !S.locked) {
      if (S.page === -1) {
        S.book.layout.cover.photo_id = id;
        markDirty();
        renderCanvas(true);
      } else {
        placeOnPage(id, S.page, false);
      }
    }
  });

  $('pv-back').addEventListener('click', () => enterEditor());
  $('pv-rerender').addEventListener('click', openPreview);
  $('pv-confirm').addEventListener('change', (e) => {
    $('pv-checkout').disabled = !e.target.checked;
  });
  $('pv-checkout').addEventListener('click', () => showScreen('checkout'));

  $('co-back').addEventListener('click', () => openPreview());
  $('co-form').addEventListener('submit', submitCheckout);

  $('or-lookup').addEventListener('submit', submitLookup);
  $('or-dev-pay').addEventListener('click', devPayNow);
  $('or-new-book').addEventListener('click', () => {
    if (confirm(t('confirm.newBook'))) {
      store('mb-book', null);
      S.creds = null;
      S.book = null;
      enterStart();
    }
  });

  window.addEventListener('resize', () => {
    if ($('screen-editor').classList.contains('active')) renderCanvas();
  });
  window.addEventListener('beforeunload', (e) => {
    if (S.dirty || S.saving) { e.preventDefault(); e.returnValue = ''; }
  });
}

async function init() {
  initLang();
  buildLangSelect();
  applyStatic();
  bind();
  const order = load('mb-order');
  if (order) S.order = order;
  enterStart();
}

init();
