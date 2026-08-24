/* Editor application. Screens: start -> editor -> preview -> checkout -> order.
   All geometry mirrors the backend (backend/app/domain/geometry.py):
   trim 148x210mm, bleed 3mm (canvas 154x216), safe margin 5mm inside trim.
   Coordinates are millimetres with the origin at the trim top-left. */
import * as api from './api.js?v=20260821';
import { LANG_NAMES, applyStatic, fmtAmount, initLang, lang, setLang, t } from './i18n.js?v=20260821';
import { STICKER_CATEGORIES, STICKERS } from './stickers.js?v=20260821';
import { DEFAULT_LAYOUT, LAYOUTS } from './layouts.js?v=20260821';
import { makeJobs, runJobs } from './upload.js?v=20260821';

const BLEED = 3, TRIM_W = 148, TRIM_H = 210, SAFE = 5;
/* Every interior page is bound along one edge, and paper curves into the
   spine there — a face placed in this strip disappears into the fold.
   PLACEHOLDER: 5mm is a sane lay-flat allowance; replace it with the
   printer's own figure (docs/printer-questions.md, question 13). */
const GUTTER = 5;
const CANVAS_W = TRIM_W + 2 * BLEED, CANVAS_H = TRIM_H + 2 * BLEED;
const PT_MM = 25.4 / 72;
const ORDER_FLOW = ['pending_payment', 'paid', 'rendering', 'rendered',
                    'sent_to_production', 'shipped', 'delivered'];
const USABLE = new Set(['ready', 'duplicate']);
const INGESTING = new Set(['pending', 'processing']);
// A photo still "processing" after this long is dead (lost job, crashed
// worker): show it as failed and stop polling for it.
const INGEST_STALL_MS = 3 * 60 * 1000;
/* The six print families — served as local woff2 (same files the renderer
   embeds), with system fallbacks while they load. */
const FONTS = {
  sans: "'DejaVu Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif",
  serif: "'DejaVu Serif', Georgia, 'Times New Roman', serif",
  mono: "'DejaVu Sans Mono', 'Courier New', Courier, monospace",
  inter: "'Inter', -apple-system, BlinkMacSystemFont, Arial, sans-serif",
  montserrat: "'Montserrat', -apple-system, Arial, sans-serif",
  notoserif: "'Noto Serif', Georgia, serif",
};
const FONT_LABELS = {
  sans: 'Sans', serif: 'Serif', mono: 'Mono',
  inter: 'Inter', montserrat: 'Montserrat', notoserif: 'Noto Serif',
};
const fontKey = (name) => (FONTS[String(name || '').toLowerCase()]
  ? String(name).toLowerCase() : 'sans');
const fontStack = (name) => FONTS[fontKey(name)];

const S = {
  creds: null, book: null, photos: [], uploads: [],
  page: -1, sel: null, locked: false, dragging: false,
  selecting: false, selected: new Set(),
  dirty: false, saving: false, saveQueued: false, saveTimer: null,
  photoTimer: null, orderTimer: null, previewTimer: null,
  pollIdle: 0, pendingSince: new Map(),
  order: null, prices: null, tiers: null, sidesPerSheet: 2,
  bookType: null, devAvailable: null,
};

/* Occasion picked before the page-count step. Everything here is only a
   STARTING POINT — a prefilled cover title and colour the customer can
   change or delete. "memory" deliberately applies nothing. */
const BOOK_TYPES = {
  love: { emoji: '❤️', bg: '#7a2740', titleColor: '#ffffff' },
  travel: { emoji: '✈️', bg: '#1d4d85', titleColor: '#ffffff' },
  birthday: { emoji: '🎂', bg: '#5b2d86', titleColor: '#ffffff' },
  memory: { emoji: '📸' },
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

/* Prices live in the backend .env (PRICE_MINOR_*); the editor only
   displays what the API reports, so both always match. */
async function loadPrices() {
  try {
    const r = await api.prices();
    S.prices = r.prices;
    S.tiers = r.tiers || null;
    S.sidesPerSheet = r.sides_per_sheet || 2;
  } catch (e) { S.prices = null; S.tiers = null; }
  renderPrices();
}

/* The customer buys sheets of paper; each sheet is printed on both sides,
   so a 16-sheet book is 32 designed pages (A63). Page count stays the unit
   everything below the picker speaks in. */
const sheetsToPages = (sheets) => sheets * (S.sidesPerSheet || 2);
const pagesToSheets = (pages) => Math.round(pages / (S.sidesPerSheet || 2));

function priceForPages(pages) {
  if (!S.prices) return null;
  // Keyed by sheet tier; books made before sheet-counting fall back to their
  // own page count, exactly as the backend prices them.
  return S.prices[String(pagesToSheets(pages))] || S.prices[String(pages)] || null;
}

function renderPrices() {
  for (const card of document.querySelectorAll('.tier')) {
    const sheets = Number(card.dataset.tier);
    const tier = (S.tiers || []).find((x) => x.sheets === sheets);
    const pages = tier ? tier.pages : sheetsToPages(sheets);
    card.dataset.pages = String(pages);
    const priceEl = card.querySelector('[data-tier-price]');
    if (priceEl) {
      const minor = tier ? tier.price_minor : priceForPages(pages);
      priceEl.textContent = minor ? fmtAmount(minor) : '';
    }
    const pagesEl = card.querySelector('[data-tier-pages]');
    if (pagesEl) pagesEl.textContent = t('start.pagesEq', { n: pages });
  }
  // The header tier picker speaks sheets too, but carries page counts.
  const sel = $('tier-select');
  if (sel && S.tiers) {
    const keep = sel.value;
    sel.innerHTML = '';
    for (const tier of S.tiers) {
      sel.append(h('option', { value: String(tier.pages) },
                   t('start.sheetsShort', { n: tier.sheets })));
    }
    if (keep) sel.value = keep;
  }
  if (S.book) {
    const minor = priceForPages(S.book.page_count);
    $('pv-price').textContent = minor ? fmtAmount(minor) : '';
  }
}

function showTypeStep() {
  S.bookType = null;
  $('type-step').classList.remove('hidden');
  $('tier-step').classList.add('hidden');
}

function pickBookType(type) {
  S.bookType = type;
  $('type-chosen').textContent =
    `${BOOK_TYPES[type].emoji} ${t(`type.${type}`)}`;
  $('type-step').classList.add('hidden');
  $('tier-step').classList.remove('hidden');
}

async function enterStart() {
  showScreen('start');
  showTypeStep();
  const offline = !(await api.health());
  $('api-offline').classList.toggle('hidden', !offline);
  for (const b of document.querySelectorAll('.tier, .btype')) b.disabled = offline;
  if (!offline && !S.prices) loadPrices();
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
    const b = await api.createBook(tier, S.bookType);
    S.creds = { book_id: b.book_id, edit_token: b.edit_token };
    store('mb-book', S.creds);
    S.book = b;
    S.photos = [];
    S.uploads = [];
    S.page = -1;
    S.sel = null;
    S.locked = false;
    const theme = BOOK_TYPES[S.bookType];
    if (theme && theme.bg) {
      const cover = S.book.layout.cover;
      if (!cover.title) cover.title = t(`type.title.${S.bookType}`);
      cover.bg_color = theme.bg;
      cover.title_color = theme.titleColor;
      markDirty();
    }
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
  for (const id of ['tier-select', 'btn-autofill', 'btn-add-text', 'btn-layout', 'file-input']) {
    $(id).disabled = S.locked;
  }
  $('btn-preview').disabled = false;
  $('upload-zone').classList.toggle('disabled', S.locked);
}

function updatePageLabel() {
  $('page-label').textContent =
    S.page === -1 ? t('page.cover') : t('page.n', { n: S.page + 1 });
  // The cover is a single fixed frame — layouts belong to inside pages.
  $('btn-layout').classList.toggle('hidden', S.page === -1 || S.locked);
}

/* What is actually missing, counted the way the layout consumes photos: a
   grid page eats four, a photo across the fold fills two (A65). */
function bookProgress() {
  const pages = S.book.layout.pages;
  const used = new Set();
  for (const page of pages) {
    for (const pl of page.placements) used.add(pl.photo_id);
  }
  if (S.book.layout.cover.photo_id) used.add(S.book.layout.cover.photo_id);
  const empty = pages.filter((p) => !p.placements.length).length;
  const unplaced = S.photos.filter(
    (p) => USABLE.has(p.status) && !used.has(p.photo_id)).length;
  return { empty, unplaced, shortfall: Math.max(0, empty - unplaced) };
}

function updateEligibility() {
  const { empty, shortfall } = bookProgress();
  const el = $('elig-banner');
  el.classList.toggle('hidden', empty === 0);
  if (shortfall > 0) el.textContent = t('elig.need', { n: shortfall });
  else if (empty > 0) el.textContent = t('elig.place', { n: empty });
}

/* ---------- tray ---------- */

function renderTray() {
  updateEligibility();
  $('tray-count').textContent = t('tray.count', { ready: usableCount() });
  const none = S.locked || S.photos.length === 0;
  $('btn-delete-all').classList.toggle('hidden', none || S.selecting);
  $('btn-select-mode').classList.toggle('hidden', none);
  $('btn-select-mode').classList.toggle('active', S.selecting);
  const delSel = $('btn-delete-sel');
  delSel.classList.toggle('hidden', !S.selecting);
  delSel.textContent = t('tray.deleteSel', { n: S.selected.size });
  delSel.disabled = S.selected.size === 0;
  const grid = $('tray-grid');
  grid.innerHTML = '';
  const placed = placedIds();
  const known = new Set(S.photos.map((p) => p.photo_id));

  for (const job of S.uploads) {
    if (job.photo_id && known.has(job.photo_id)) continue;   // server card exists
    const card = h('div', { class: `ph-card job ${job.status}` });
    if (job.status === 'failed') {
      card.append(h('span', { class: 'badge err' }, t('tray.failed')));
      card.append(h('button', {
        class: 'ph-del', 'aria-label': t('tool.remove'),
        onclick: (e) => {
          e.stopPropagation();
          S.uploads = S.uploads.filter((j) => j !== job);
          renderTray();
        },
      }, '×'));
    } else {
      card.append(h('span', { class: 'spin' }), h('span', { class: 'badge' }, t('tray.processing')));
    }
    card.append(h('span', { class: 'ph-name' }, job.name));
    grid.append(card);
  }

  for (const p of S.photos) {
    const card = h('div', {
      class: 'ph-card' + (USABLE.has(p.status) ? '' : ' pending')
        + (S.selecting && S.selected.has(p.photo_id) ? ' picked' : ''),
      title: p.width && p.height ? `${p.width}×${p.height} px` : null,
      draggable: USABLE.has(p.status) && !S.locked && !S.selecting ? 'true' : null,
      ondragstart: (e) => e.dataTransfer.setData('text/mb-photo', p.photo_id),
      onclick: () => {
        if (S.locked) return;
        if (S.selecting) {
          if (S.selected.has(p.photo_id)) S.selected.delete(p.photo_id);
          else S.selected.add(p.photo_id);
          renderTray();
          return;
        }
        if (USABLE.has(p.status)) placePhoto(p);
      },
    });
    if (p.thumb_url) {
      card.append(h('img', { src: p.thumb_url, alt: '', loading: 'lazy' }));
    }
    if (p.status === 'failed' || ingestStuck(p)) {
      card.append(h('span', { class: 'badge err' }, t('tray.failed')));
    } else if (INGESTING.has(p.status)) {
      card.append(h('span', { class: 'spin' }));
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

async function deletePhotoIds(ids, btn) {
  btn.disabled = true;
  const queue = [...ids];
  let failed = 0;
  await Promise.all(Array.from({ length: 4 }, async () => {
    for (;;) {
      const id = queue.shift();
      if (!id) return;
      try {
        await api.deletePhoto(S.creds, id);
      } catch (e) {
        failed += 1;
      }
    }
  }));
  try {
    const r = await api.listPhotos(S.creds);
    S.photos = r.photos;
  } catch (e) { /* keep local view; poll will catch up */ }
  const remaining = new Set(S.photos.map((p) => p.photo_id));
  let touched = false;
  for (const page of S.book.layout.pages) {
    const before = page.placements.length;
    page.placements = page.placements.filter((pl) => remaining.has(pl.photo_id));
    if (page.placements.length !== before) touched = true;
  }
  if (S.book.layout.cover.photo_id && !remaining.has(S.book.layout.cover.photo_id)) {
    S.book.layout.cover.photo_id = null;
    touched = true;
  }
  S.sel = null;
  S.selected.clear();
  S.selecting = false;
  if (touched) markDirty();
  btn.disabled = false;
  if (failed) toast(t('err.generic'), 'warn');
  renderAll();
}

async function deleteAllPhotos() {
  if (S.locked || !S.photos.length) return;
  if (!confirm(t('confirm.deleteAll'))) return;
  S.uploads = [];
  await deletePhotoIds(S.photos.map((p) => p.photo_id), $('btn-delete-all'));
}

async function deleteSelectedPhotos() {
  if (S.locked || !S.selected.size) return;
  if (!confirm(t('confirm.deleteSel', { n: S.selected.size }))) return;
  await deletePhotoIds([...S.selected], $('btn-delete-sel'));
}

function schedulePhotoPoll() {
  if (S.photoTimer) return;
  S.photoTimer = setTimeout(pollPhotos, 1500);
}

function ingestStuck(p) {
  return INGESTING.has(p.status)
    && Date.now() - (S.pendingSince.get(p.photo_id) || Date.now()) >= INGEST_STALL_MS;
}

// Statuses only — presigned thumb URLs differ on every response, so they
// must stay out of this or every poll would count as a change.
function photoFingerprint() {
  return S.photos.map((p) =>
    `${p.photo_id}:${p.status}:${p.resolution_status || ''}:${ingestStuck(p) ? 1 : 0}`).join('|');
}

async function pollPhotos() {
  S.photoTimer = null;
  if (!S.creds) return;
  const before = photoFingerprint();
  try {
    const r = await api.listPhotos(S.creds);
    S.photos = r.photos;
  } catch (e) { /* transient; next poll retries */ }
  const now = Date.now();
  for (const p of S.photos) {
    if (!INGESTING.has(p.status)) {
      S.pendingSince.delete(p.photo_id);
    } else if (!S.pendingSince.has(p.photo_id)) {
      // Seed from the server timestamp so photos that stalled before this
      // page load are flagged immediately, not 3 minutes from now.
      const started = Date.parse(p.uploaded_at || '');
      S.pendingSince.set(p.photo_id, Number.isFinite(started) ? started : now);
    }
  }
  // Re-render only on real change — rebuilding the tray refetches every
  // thumbnail (fresh presigned URLs), which reads as flicker.
  if (photoFingerprint() !== before) {
    S.pollIdle = 0;
    if ($('screen-editor').classList.contains('active')) {
      renderTray();
      renderFilm();
      renderCanvas();
    }
  } else {
    S.pollIdle += 1;
  }
  const busy = S.photos.some((p) => INGESTING.has(p.status) && !ingestStuck(p))
    || S.uploads.some((j) => j.status === 'queued' || j.status === 'uploading');
  if (busy) {
    // Back off while nothing changes: 1.5s -> 3s -> ... -> 10s max.
    S.photoTimer = setTimeout(pollPhotos, Math.min(1500 * (S.pollIdle + 1), 10000));
  }
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

function placeOnPage(photoId, index, advance, slotIdx = null) {
  const page = S.book.layout.pages[index];
  const slots = pageSlots(page);
  const wasEmpty = page.placements.length === 0;
  const shot = (slot) => ({ photo_id: photoId, ...slot, rotation: 0, fit: 'cover' });
  if (slotIdx !== null && slotIdx < page.placements.length) {
    page.placements[slotIdx] = shot(slots[slotIdx]);          // replace that photo
  } else if (page.placements.length < slots.length) {
    page.placements.push(shot(slots[page.placements.length])); // next empty slot
  } else {
    // Page is full: replace the selected photo, else the last one.
    const target = S.sel && S.sel.kind === 'placement' ? S.sel.idx : slots.length - 1;
    page.placements[target] = shot(slots[target]);
  }
  markDirty();
  // Only move on once this page has nothing left to fill.
  if (advance && wasEmpty && page.placements.length >= slots.length) {
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


/* ---------- spreads: two facing pages ---------- */

/* Bound, page 1 stands alone on the right; after that pages pair up
   (2,3), (4,5)... In zero-based indices page 0 is alone, then (1,2),
   (3,4)... A photo may run across the fold of any real pair (A65). */
function facingPage(index) {
  if (index < 1) return -1;                     // page 1 has no partner
  const partner = index % 2 === 1 ? index + 1 : index - 1;
  return partner < S.book.layout.pages.length ? partner : -1;
}

const isLeftPage = (index) => index % 2 === 1;

/* Page 1 is a right-hand page bound on its left; left-hand pages are bound
   on the right. The strip covers the bleed plus the gutter allowance. */
function gutterGuide(index) {
  return h('div', {
    class: 'guide gutter ' + (isLeftPage(index) ? 'bound-right' : 'bound-left'),
    style: `width:${pct(BLEED + GUTTER, CANVAS_W)}`,
  });
}

/* The full-spread rectangle as this page sees it: the photo starts at the
   left page's bleed edge, so the right page holds the same rectangle
   shifted back by one trim width. */
function spreadRect(index) {
  return {
    x_mm: isLeftPage(index) ? -BLEED : -BLEED - TRIM_W,
    y_mm: -BLEED,
    w_mm: 2 * TRIM_W + 2 * BLEED,
    h_mm: TRIM_H + 2 * BLEED,
  };
}

const spreadHalf = (page, id) =>
  (page ? page.placements.find((pl) => pl.spread_id === id) : null) || null;

/* Make the selected photo run across the fold: both pages carry the same
   photo, cropped as one, each showing the half that falls on it. */
function spanAcrossFold(pl) {
  const partnerIdx = facingPage(S.page);
  if (partnerIdx === -1 || S.locked) return;
  const page = S.book.layout.pages[S.page];
  const partner = S.book.layout.pages[partnerIdx];
  const id = `sp${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`;
  const shared = {
    photo_id: pl.photo_id, rotation: 0, fit: 'cover',
    zoom: pl.zoom || 1, focus_x: pl.focus_x ?? 0.5, focus_y: pl.focus_y ?? 0.5,
    spread_id: id,
  };
  // A spread photo owns both pages outright.
  page.layout = 'full';
  partner.layout = 'full';
  page.placements = [{ ...shared, ...spreadRect(S.page) }];
  partner.placements = [{ ...shared, ...spreadRect(partnerIdx) }];
  S.sel = { kind: 'placement', idx: 0 };
  markDirty();
  renderCanvas(true);
  renderFilm();
  renderTray();
}

/* Back to a photo on this page alone; the facing page is left empty. */
function unspanFold(pl) {
  const partnerIdx = facingPage(S.page);
  const partner = partnerIdx === -1 ? null : S.book.layout.pages[partnerIdx];
  const other = spreadHalf(partner, pl.spread_id);
  if (other) partner.placements.splice(partner.placements.indexOf(other), 1);
  const page = S.book.layout.pages[S.page];
  pl.spread_id = null;
  Object.assign(pl, pageSlots(page)[0]);
  markDirty();
  renderCanvas(true);
  renderFilm();
  renderTray();
}

/* Keep the far half of a spread photo in step with the one being edited. */
function syncSpreadHalf(pl) {
  if (!pl.spread_id) return;
  const partnerIdx = facingPage(S.page);
  if (partnerIdx === -1) return;
  const other = spreadHalf(S.book.layout.pages[partnerIdx], pl.spread_id);
  if (!other) return;
  other.zoom = pl.zoom;
  other.focus_x = pl.focus_x;
  other.focus_y = pl.focus_y;
  other.photo_id = pl.photo_id;
  Object.assign(other, spreadRect(partnerIdx));
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
  renderFacingPage();
  renderPageTools();
  renderSelToolbar();
}

/* The facing page, shown beside the one being edited so the spread reads as
   the customer will hold it. It is a picture, not an editor: tapping it
   moves editing there. */
function renderFacingPage() {
  const wrap = $('canvas-wrap');
  const partnerIdx = S.page === -1 ? -1 : facingPage(S.page);
  wrap.classList.toggle('spread', partnerIdx !== -1);
  if (partnerIdx !== -1) wrap.classList.toggle('flip', !isLeftPage(S.page));
  const old = $('facing-canvas');
  if (old) old.remove();
  if (partnerIdx === -1) return;

  const el = h('div', { class: 'page-canvas facing', id: 'facing-canvas',
                        title: t('spread.goFacing') });
  el.style.background = S.book.layout.pages[partnerIdx].bg_color || '#ffffff';
  el.addEventListener('click', () => {
    S.page = partnerIdx;
    S.sel = null;
    renderCanvas(true);
    renderFilm();
  });
  wrap.append(el);
  renderStaticPage(el, S.book.layout.pages[partnerIdx]);
  el.append(h('div', { class: 'facing-label' },
              t('spread.page', { n: partnerIdx + 1 })));
}

/* Draw a page's content with no handles and no handlers — used for the
   facing page, whose job is to show the join, not to be edited. */
function renderStaticPage(el, page) {
  const scale = el.clientWidth / CANVAS_W;
  el.append(gutterGuide(page.index));
  for (const pl of page.placements) {
    const box = h('div', { class: 'placement' });
    placeRect(box, pl);
    const photo = photoById(pl.photo_id);
    if (photo && photo.display_url) {
      box.append(h('img', { src: photo.display_url, alt: '', draggable: 'false' }));
    }
    el.append(box);
    applyCrop(box, pl);
  }
  for (const st of page.stickers || []) {
    const sticker = h('div', { class: 'sticker' });
    sticker.style.left = pct(st.x_mm + BLEED - st.w_mm / 2, CANVAS_W);
    sticker.style.top = pct(st.y_mm + BLEED - st.w_mm / 2, CANVAS_H);
    sticker.style.width = pct(st.w_mm, CANVAS_W);
    if (st.rotation) sticker.style.transform = `rotate(${st.rotation}deg)`;
    sticker.append(h('img', { src: `stickers/${st.sticker_id}.png`, alt: '' }));
    el.append(sticker);
  }
  for (const tb of page.texts) {
    el.append(h('div', {
      class: 'textbox static',
      style: `left:${pct(tb.x_mm + BLEED, CANVAS_W)};top:${pct(tb.y_mm + BLEED, CANVAS_H)};`
        + `width:${pct(tb.w_mm, CANVAS_W)};font-size:${tb.size_pt * PT_MM * scale}px;`
        + `text-align:${tb.align};color:${tb.color};font-family:${fontStack(tb.font)}`
        + (tb.rotation ? `;transform:rotate(${tb.rotation}deg)` : ''),
    }, h('div', { class: 'textbox-content' }, tb.content)));
  }
}

/* Always-available colour controls for the current page / the cover. */
function renderPageTools() {
  const box = $('page-tools');
  box.innerHTML = '';
  if (S.locked) return;
  const colorInput = (value, label, oninput, onchange) => colorControl(
    value, label, (colour) => { oninput(colour); if (onchange) onchange(colour); });
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
  }
  const scale = canvas.clientWidth / CANVAS_W;   // px per mm
  const textColor = cover.title_color || (photo ? '#ffffff' : '#1a1a1a');
  const cx = cover.title_x_mm ?? TRIM_W / 2;
  const cy = cover.title_y_mm ?? 122;
  const rot = cover.title_rotation || 0;
  const selected = S.sel && S.sel.kind === 'cover';

  const titles = h('div', { class: 'cover-titles' + (selected ? ' sel' : '')
    + (cy < 28 ? ' flip' : '') });
  titles.style.left = pct(cx + BLEED, CANVAS_W);
  titles.style.top = pct(cy + BLEED, CANVAS_H);
  titles.style.transform = 'translate(-50%, -50%)' + (rot ? ` rotate(${rot}deg)` : '');

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
  for (const input of [title, subtitle]) {
    input.addEventListener('focus', () => select({ kind: 'cover' }, true));
  }
  titles.append(title, subtitle);

  // Shared drag starter — used by the block body (when not typing) and by
  // the ⠿ handle (always, even while the caret is in an input).
  const beginDrag = (e, focusOnStillClick) => {
    e.preventDefault();
    e.stopPropagation();
    S.dragging = true;
    const snap = makeSnap();
    const sx = e.clientX, sy = e.clientY;
    const ox = cover.title_x_mm ?? TRIM_W / 2;
    const oy = cover.title_y_mm ?? 122;
    let moved = false;
    const move = (ev) => {
      if (S.pinching) return;
      if (!moved && Math.hypot(ev.clientX - sx, ev.clientY - sy) < 4) return;
      moved = true;
      const cx = snap.axis('x', ox + (ev.clientX - sx) / scale, TRIM_W / 2);
      const cy = snap.axis('y', oy + (ev.clientY - sy) / scale, TRIM_H / 2);
      cover.title_x_mm = clamp(Math.round(cx * 10) / 10, SAFE, TRIM_W - SAFE);
      cover.title_y_mm = clamp(Math.round(cy * 10) / 10, SAFE, TRIM_H - SAFE);
      titles.style.left = pct(cover.title_x_mm + BLEED, CANVAS_W);
      titles.style.top = pct(cover.title_y_mm + BLEED, CANVAS_H);
      snap.guides(cover.title_x_mm, cover.title_y_mm);
    };
    const up = () => {
      S.dragging = false;
      clearSnapGuides();
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      if (moved) markDirty();
      else if (focusOnStillClick && titles.isConnected) {
        select({ kind: 'cover' });
        // Synchronous: typing may start immediately after the tap.
        const el = document.querySelector('.cover-title');
        if (el) el.focus();
      }
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  // Drag the block anywhere; a still click starts typing in the title.
  titles.addEventListener('pointerdown', (e) => {
    if (S.locked || !e.isPrimary) return;
    if (document.activeElement === title || document.activeElement === subtitle) return;
    if (e.target.closest('.tb-rotate, .tb-scale, .tb-handle')) return;
    beginDrag(e, true);
  });

  // The ⠿ handle: always drags — including mid-typing, where the body
  // gives way to text editing.
  const moveHandle = h('div', { class: 'tb-handle' }, '⠿');
  moveHandle.addEventListener('pointerdown', (e) => {
    if (S.locked || !e.isPrimary) return;
    beginDrag(e, false);
  });
  titles.append(moveHandle);

  if (selected && !S.locked) {
    const rotate = h('div', { class: 'tb-rotate' }, '⟳');
    rotate.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      e.stopPropagation();
      S.dragging = true;
      const r = titles.getBoundingClientRect();
      const ccx = r.left + r.width / 2, ccy = r.top + r.height / 2;
      const start = (Math.atan2(e.clientY - ccy, e.clientX - ccx) * 180) / Math.PI;
      const orig = cover.title_rotation || 0;
      const move = (ev) => {
        if (S.pinching) return;
        const a = (Math.atan2(ev.clientY - ccy, ev.clientX - ccx) * 180) / Math.PI;
        cover.title_rotation = normDeg(orig + (a - start));
        titles.style.transform = 'translate(-50%, -50%)'
          + (cover.title_rotation ? ` rotate(${cover.title_rotation}deg)` : '');
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

    const scaleH = h('div', { class: 'tb-scale' });
    scaleH.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      e.stopPropagation();
      S.dragging = true;
      const r = titles.getBoundingClientRect();
      const ccx = r.left + r.width / 2, ccy = r.top + r.height / 2;
      const d0 = Math.max(8, Math.hypot(e.clientX - ccx, e.clientY - ccy));
      const origSize = cover.title_size_pt;
      const move = (ev) => {
        if (S.pinching) return;
        const f = clamp(Math.hypot(ev.clientX - ccx, ev.clientY - ccy) / d0, 0.25, 6);
        cover.title_size_pt = clamp(Math.round(origSize * f), 4, 144);
        title.style.fontSize = `${cover.title_size_pt * PT_MM * scale}px`;
        subtitle.style.fontSize = `${0.5 * cover.title_size_pt * PT_MM * scale}px`;
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
    });
    titles.append(rotate, scaleH);
  }

  attachPinch(titles, {
    getState: () => ({ size: cover.title_size_pt, rot: cover.title_rotation || 0 }),
    apply: (f, da, o) => {
      cover.title_size_pt = clamp(Math.round(o.size * f), 4, 144);
      cover.title_rotation = normDeg(o.rot + da);
      title.style.fontSize = `${cover.title_size_pt * PT_MM * scale}px`;
      subtitle.style.fontSize = `${0.5 * cover.title_size_pt * PT_MM * scale}px`;
      titles.style.transform = 'translate(-50%, -50%)'
        + (cover.title_rotation ? ` rotate(${cover.title_rotation}deg)` : '');
    },
    end: () => { markDirty(); renderCanvas(true); renderSelToolbar(); },
  });

  for (const st of cover.stickers || []) {
    canvas.append(makeSticker(st, cover.stickers));
  }
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

  const slots = pageSlots(page);
  canvas.append(gutterGuide(S.page));
  page.placements.forEach((pl, i) => canvas.append(makePlacement(pl, i)));
  for (let i = page.placements.length; i < slots.length; i += 1) {
    canvas.append(makeEmptySlot(slots[i]));
  }

  // Stickers stack above the photo, below text — matching the print PDFs.
  for (const st of page.stickers || []) {
    canvas.append(makeSticker(st, page.stickers));
  }

  const scale = canvas.clientWidth / CANVAS_W;   // px per mm
  for (const tb of page.texts) {
    canvas.append(makeTextBox(tb, scale));
  }
}

/* ---------- page layouts ---------- */

/* A layout is a named set of slot rectangles (shared with the renderer via
   layouts.js). Placements fill slots in order — placements[i] lives in
   slots[i] — so the trailing slots are the empty ones and the document can
   never describe a hole. */
const pageLayoutId = (page) => (LAYOUTS[page.layout] ? page.layout : DEFAULT_LAYOUT);
const pageSlots = (page) => LAYOUTS[pageLayoutId(page)];

function reflowSlots(page) {
  const slots = pageSlots(page);
  page.placements.forEach((pl, i) => {
    // A photo crossing the fold keeps its spread rectangle; slot geometry
    // would pull it back onto this page and break the join.
    if (!pl.spread_id) Object.assign(pl, slots[i]);
  });
}

function slotIndexAt(clientX, clientY, page) {
  const canvas = $('page-canvas');
  if (!canvas) return -1;
  const r = canvas.getBoundingClientRect();
  const mmX = ((clientX - r.left) / (r.width / CANVAS_W)) - BLEED;
  const mmY = ((clientY - r.top) / (r.height / CANVAS_H)) - BLEED;
  return pageSlots(page).findIndex(
    (sl) => mmX >= sl.x_mm && mmX <= sl.x_mm + sl.w_mm
         && mmY >= sl.y_mm && mmY <= sl.y_mm + sl.h_mm);
}

function applyLayout(id) {
  if (S.page === -1 || S.locked || !LAYOUTS[id]) return;
  const page = S.book.layout.pages[S.page];
  // Slots belong to one page, so picking a grid ends a photo's span.
  const spanning = page.placements.find((pl) => pl.spread_id);
  if (spanning) unspanFold(spanning);
  const slots = LAYOUTS[id];
  // Photos beyond the new slot count go back to the tray, never vanish.
  page.placements = page.placements.slice(0, slots.length);
  page.layout = id;
  reflowSlots(page);
  S.sel = null;
  markDirty();
  renderCanvas(true);
  renderFilm();
  renderTray();
}

/* Miniature of a layout, drawn from the same slot geometry it applies. */
function layoutThumb(id) {
  const box = h('div', { class: 'lay-thumb' });
  for (const sl of LAYOUTS[id]) {
    box.append(h('div', {
      class: 'lay-cell',
      style: `left:${pct(sl.x_mm + BLEED, CANVAS_W)};top:${pct(sl.y_mm + BLEED, CANVAS_H)};`
           + `width:${pct(sl.w_mm, CANVAS_W)};height:${pct(sl.h_mm, CANVAS_H)}`,
    }));
  }
  return box;
}

function closeLayoutPop() {
  const open = document.querySelector('.layout-pop');
  if (open) open.remove();
  document.removeEventListener('pointerdown', outsideLayoutClose, true);
}

function outsideLayoutClose(e) {
  if (!e.target.closest('.layout-pop, #btn-layout')) closeLayoutPop();
}

function openLayoutPop(btn) {
  if (document.querySelector('.layout-pop')) { closeLayoutPop(); return; }
  const page = S.book.layout.pages[S.page];
  const current = pageLayoutId(page);
  const pop = h('div', { class: 'layout-pop' });
  for (const id of Object.keys(LAYOUTS)) {
    pop.append(h('button', {
      class: 'lay-item' + (id === current ? ' active' : ''),
      type: 'button', 'aria-label': id,
      onclick: () => { applyLayout(id); closeLayoutPop(); },
    }, layoutThumb(id)));
  }
  document.body.append(pop);
  const r = btn.getBoundingClientRect();
  pop.style.left = `${Math.max(8, Math.min(window.innerWidth - pop.offsetWidth - 8, r.left))}px`;
  pop.style.top = `${Math.min(window.innerHeight - pop.offsetHeight - 8, r.bottom + 6)}px`;
  setTimeout(() => document.addEventListener('pointerdown', outsideLayoutClose, true), 0);
}

/* ---------- centre snapping ---------- */

/* Dragged elements are magnetically held at the page centre: they latch on
   within GRAB pixels and only let go past HOLD pixels, so centring is easy
   to hit and hard to lose by a shaky finger. Guides show while latched. */
const SNAP_GRAB_PX = 9;
const SNAP_HOLD_PX = 22;

function makeSnap() {
  const scale = canvasScale();
  const grab = SNAP_GRAB_PX / scale;
  const hold = SNAP_HOLD_PX / scale;
  const stuck = { x: false, y: false };
  return {
    /* centre coordinate on one axis -> snapped coordinate */
    axis(axis, value, target) {
      const near = Math.abs(value - target) < (stuck[axis] ? hold : grab);
      stuck[axis] = near;
      return near ? target : value;
    },
    /* call with the FINAL centre, after clamping, so guides never lie */
    guides(cx, cy) {
      setSnapGuides(stuck.x && Math.abs(cx - TRIM_W / 2) < 0.05,
                    stuck.y && Math.abs(cy - TRIM_H / 2) < 0.05);
    },
  };
}

function setSnapGuides(showV, showH) {
  const canvas = $('page-canvas');
  if (!canvas) return;
  for (const [cls, on] of [['v', showV], ['h', showH]]) {
    const existing = canvas.querySelector(`.snap-guide.${cls}`);
    if (on && !existing) canvas.append(h('div', { class: `snap-guide ${cls}` }));
    else if (!on && existing) existing.remove();
  }
}

const clearSnapGuides = () => setSnapGuides(false, false);

/* ---------- colour control ---------- */

/* Native <input type=color> opens a fiddly OS dialog on phones. A grid of
   large swatches is one tap; the native picker stays available behind
   "Custom" for anyone who wants an exact shade. */
const SWATCHES = [
  '#ffffff', '#f7f3ea', '#e8e8e8', '#9aa0a6', '#4a4f57', '#1a1a1a',
  '#7a2740', '#c0392b', '#e07a3f', '#d9a441', '#3f7a44', '#2f6f6b',
  '#1d4d85', '#2456d6', '#5b2d86', '#c66591',
];

function closeSwatchPop() {
  const open = document.querySelector('.swatch-pop');
  if (open) open.remove();
  document.removeEventListener('pointerdown', outsideSwatchClose, true);
}

function outsideSwatchClose(e) {
  if (!e.target.closest('.swatch-pop, .color-tool')) closeSwatchPop();
}

function colorControl(value, label, onPick) {
  const dot = h('span', { class: 'color-dot', style: `background:${value}` });
  const btn = h('button', { class: 'color-tool btn small', type: 'button' },
                dot, h('span', {}, label));
  btn.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (document.querySelector('.swatch-pop')) { closeSwatchPop(); return; }
    const pop = h('div', { class: 'swatch-pop' });
    const apply = (colour) => {
      dot.style.background = colour;
      onPick(colour);
    };
    const grid = h('div', { class: 'swatch-grid' });
    for (const colour of SWATCHES) {
      grid.append(h('button', {
        class: 'swatch' + (colour === (value || '').toLowerCase() ? ' active' : ''),
        type: 'button', style: `background:${colour}`, 'aria-label': colour,
        onclick: () => { apply(colour); closeSwatchPop(); },
      }));
    }
    const custom = h('input', { type: 'color', value: value || '#ffffff' });
    custom.addEventListener('input', () => apply(custom.value));
    pop.append(grid, h('label', { class: 'swatch-more' },
                       custom, h('span', {}, t('tool.customColor'))));
    document.body.append(pop);
    const r = btn.getBoundingClientRect();
    const width = pop.offsetWidth;
    pop.style.left = `${Math.max(8, Math.min(window.innerWidth - width - 8, r.left))}px`;
    pop.style.top = `${Math.min(window.innerHeight - pop.offsetHeight - 8, r.bottom + 6)}px`;
    setTimeout(() => document.addEventListener('pointerdown', outsideSwatchClose, true), 0);
  });
  return btn;
}

/* ---------- stickers ---------- */

function makeSticker(st, owner) {
  const el = h('div', {
    class: 'sticker' + (isSel('sticker', st.id) ? ' sel' : ''),
    'data-id': st.id,
  });
  const setStyle = () => {
    el.style.left = pct(st.x_mm + BLEED - st.w_mm / 2, CANVAS_W);
    el.style.top = pct(st.y_mm + BLEED - st.w_mm / 2, CANVAS_H);
    el.style.width = pct(st.w_mm, CANVAS_W);
    el.style.transform = st.rotation ? `rotate(${st.rotation}deg)` : '';
    el.classList.toggle('flip', st.y_mm - st.w_mm / 2 < 18);
  };
  setStyle();
  el.append(h('img', { src: `stickers/${st.sticker_id}.png`, alt: '',
                       draggable: 'false' }));

  el.addEventListener('pointerdown', (e) => {
    if (S.locked || !e.isPrimary) return;
    if (e.target.closest('.tb-rotate, .tb-scale')) return;
    e.preventDefault();
    e.stopPropagation();
    select({ kind: 'sticker', id: st.id }, true);
    const scale = canvasScale();
    const snap = makeSnap();
    const sx = e.clientX, sy = e.clientY, ox = st.x_mm, oy = st.y_mm;
    S.dragging = true;
    const move = (ev) => {
      if (S.pinching) return;
      st.x_mm = clamp(snap.axis('x', ox + (ev.clientX - sx) / scale, TRIM_W / 2), -40, 194);
      st.y_mm = clamp(snap.axis('y', oy + (ev.clientY - sy) / scale, TRIM_H / 2), -40, 256);
      setStyle();
      snap.guides(st.x_mm, st.y_mm);
    };
    const up = () => {
      S.dragging = false;
      clearSnapGuides();
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      markDirty();
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });

  const rotate = h('div', { class: 'tb-rotate' }, '⟳');
  rotate.addEventListener('pointerdown', (e) => {
    if (S.locked) return;
    e.preventDefault();
    e.stopPropagation();
    startTextRotate(e, el, st);   // same field names: rotation + transform
  });

  const scaleH = h('div', { class: 'tb-scale' });
  scaleH.addEventListener('pointerdown', (e) => {
    if (S.locked) return;
    e.preventDefault();
    e.stopPropagation();
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const d0 = Math.max(8, Math.hypot(e.clientX - cx, e.clientY - cy));
    const ow = st.w_mm;
    S.dragging = true;
    const move = (ev) => {
      const f = clamp(Math.hypot(ev.clientX - cx, ev.clientY - cy) / d0, 0.2, 8);
      st.w_mm = clamp(ow * f, 5, 80);
      setStyle();
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

  el.append(rotate, scaleH);

  attachPinch(el, {
    getState: () => ({ w: st.w_mm, rot: st.rotation || 0 }),
    apply: (f, da, o) => {
      st.w_mm = clamp(o.w * f, 5, 80);
      st.rotation = normDeg(o.rot + da);
      setStyle();
    },
    end: () => { markDirty(); renderCanvas(true); },
  });
  return el;
}

function currentStickerList() {
  if (S.page === -1) {
    const cover = S.book.layout.cover;
    if (!cover.stickers) cover.stickers = [];
    return cover.stickers;
  }
  const page = S.book.layout.pages[S.page];
  if (!page.stickers) page.stickers = [];
  return page.stickers;
}

const CATEGORY_EMOJI = {
  flags: '🇺🇿', maps: '🗺️', travel: '✈️', love: '❤️',
  birthday: '🎂', nature: '🌸', party: '🎉', misc: '⭐',
};
let stickerTab = null;

function buildStickerPanel() {
  const tabs = $('sp-tabs');
  tabs.innerHTML = '';
  for (const cat of STICKER_CATEGORIES) {
    tabs.append(h('button', {
      class: 'sp-tab' + (cat === stickerTab ? ' active' : ''),
      onclick: () => { stickerTab = cat; buildStickerPanel(); },
    }, CATEGORY_EMOJI[cat] || cat));
  }
  const grid = $('sp-grid');
  grid.innerHTML = '';
  for (const [sid, cat] of Object.entries(STICKERS)) {
    if (cat !== stickerTab) continue;
    grid.append(h('button', {
      class: 'sp-item',
      onclick: () => addSticker(sid),
    }, h('img', { src: `stickers/thumb/${sid}.png`, alt: sid, loading: 'lazy' })));
  }
}

/* Canva-style side panel: the tray switches between Photos and Stickers. */
function setTrayTab(tab) {
  $('tab-photos').classList.toggle('active', tab === 'photos');
  $('tab-stickers').classList.toggle('active', tab === 'stickers');
  $('tray-photos').classList.toggle('hidden', tab !== 'photos');
  $('tray-stickers').classList.toggle('hidden', tab !== 'stickers');
  if (tab === 'stickers') {
    if (!stickerTab) {
      // Open on the pack that matches the occasion; travel books get flags.
      stickerTab = { travel: 'flags', love: 'love', birthday: 'birthday' }[S.bookType]
        || 'flags';
    }
    buildStickerPanel();
  }
}

function addSticker(stickerId) {
  if (S.locked) return;
  const list = currentStickerList();
  if (list.length >= 20) { toast(t('err.generic'), 'warn'); return; }
  const st = {
    id: `s${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`,
    sticker_id: stickerId,
    x_mm: TRIM_W / 2, y_mm: TRIM_H / 2, w_mm: 24, rotation: 0,
  };
  list.push(st);
  S.sel = { kind: 'sticker', id: st.id };
  markDirty();
  renderCanvas(true);
}

/* How many px of photo hang outside the frame, per axis, at the current
   zoom. Zero on an axis means there is nothing to pan there. */
function cropOverflow(pl, photo) {
  if (!photo || !photo.width || !photo.height) return { x: 0, y: 0 };
  const s = canvasScale();
  const bw = pl.w_mm * s, bh = pl.h_mm * s;
  const scale = Math.max(bw / photo.width, bh / photo.height)
    * Math.max(1, pl.zoom || 1);
  return { x: Math.max(0, photo.width * scale - bw),
           y: Math.max(0, photo.height * scale - bh) };
}

/* Lay the photo inside its frame with the same arithmetic the print
   renderer uses (app/render/compose.py:_fit_cover), so what the customer
   frames on screen is exactly what gets printed. */
function applyCrop(el, pl) {
  const img = el.querySelector('img');
  if (!img) return;
  const photo = photoById(pl.photo_id);
  if (pl.fit === 'contain' || !photo || !photo.width || !photo.height) {
    img.removeAttribute('style');
    img.style.objectFit = pl.fit === 'contain' ? 'contain' : 'cover';
    return;
  }
  const s = canvasScale();
  const bw = pl.w_mm * s, bh = pl.h_mm * s;
  const scale = Math.max(bw / photo.width, bh / photo.height)
    * Math.max(1, pl.zoom || 1);
  const rw = Math.max(bw, photo.width * scale);
  const rh = Math.max(bh, photo.height * scale);
  const fx = clamp(pl.focus_x ?? 0.5, 0, 1);
  const fy = clamp(pl.focus_y ?? 0.5, 0, 1);
  img.style.position = 'absolute';
  img.style.maxWidth = 'none';
  img.style.objectFit = 'fill';
  img.style.width = `${rw}px`;
  img.style.height = `${rh}px`;
  img.style.left = `${-(rw - bw) * fx}px`;
  img.style.top = `${-(rh - bh) * fy}px`;
}

function placeRect(el, r) {
  applyCrop(el, r);
  el.style.left = pct(r.x_mm + BLEED, CANVAS_W);
  el.style.top = pct(r.y_mm + BLEED, CANVAS_H);
  el.style.width = pct(r.w_mm, CANVAS_W);
  el.style.height = pct(r.h_mm, CANVAS_H);
}

/* An empty slot of a multi-photo layout: a drop target and a hint that
   something belongs here. Tapping it opens the photo tray. */
function makeEmptySlot(slot) {
  const box = h('div', {
    class: 'slot-empty',
    onclick: () => { if (!S.locked) setTrayTab('photos'); },
    ondragover: (e) => e.preventDefault(),
    ondrop: (e) => {
      e.preventDefault();
      const id = e.dataTransfer.getData('text/mb-photo');
      if (id && !S.locked) placeOnPage(id, S.page, false);
    },
  }, h('span', {}, '+'));
  placeRect(box, slot);
  return box;
}

function makePlacement(pl, idx) {
  const photo = photoById(pl.photo_id);
  const page = S.book.layout.pages[S.page];
  const multi = pageSlots(page).length > 1;
  const box = h('div', {
    class: 'placement' + (isSel('placement', idx) ? ' sel' : ''),
    'data-idx': String(idx),
    ondragover: (e) => e.preventDefault(),
    ondrop: (e) => {
      e.preventDefault();
      const id = e.dataTransfer.getData('text/mb-photo');
      if (id && !S.locked) placeOnPage(id, S.page, false, idx);
    },
  });
  if (photo && photo.display_url) {
    box.append(h('img', { src: photo.display_url, alt: '', draggable: 'false' }));
  } else {
    box.append(h('span', { class: 'spin' }));
  }
  placeRect(box, pl);   // also lays the photo out inside the frame

  // Pan the crop: the frame is fixed (a layout slot, or a rectangle the
  // customer sized), so what moves is the photo behind it.
  if (isSel('placement', idx) && !S.locked && pl.fit !== 'contain'
      && cropOverflow(pl, photo)) {
    const pan = h('div', { class: 'pl-pan', 'data-i18n-title': 'tool.pan' }, '⠿');
    pan.title = t('tool.pan');
    pan.addEventListener('pointerdown', (e) => {
      if (S.locked || !e.isPrimary) return;
      e.preventDefault();
      e.stopPropagation();
      const over = cropOverflow(pl, photo);
      const sx = e.clientX, sy = e.clientY;
      const ofx = pl.focus_x ?? 0.5, ofy = pl.focus_y ?? 0.5;
      S.dragging = true;
      const move = (ev) => {
        if (S.pinching) return;
        // Drag right -> reveal more of the photo's left side.
        if (over.x > 0) pl.focus_x = clamp(ofx - (ev.clientX - sx) / over.x, 0, 1);
        if (over.y > 0) pl.focus_y = clamp(ofy - (ev.clientY - sy) / over.y, 0, 1);
        placeRect(box, pl);
      };
      const up = () => {
        S.dragging = false;
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        syncSpreadHalf(pl);
        markDirty();
        renderCanvas(true);      // redraw the facing half with the new crop
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    });
    box.append(pan);
  }

  // In a grid, dragging a photo swaps it with the slot it is dropped on —
  // free positioning would only let the user break the grid.
  if (multi) {
    box.addEventListener('pointerdown', (e) => {
      if (S.locked || !e.isPrimary) return;
      e.preventDefault();
      e.stopPropagation();
      const sx = e.clientX, sy = e.clientY;
      let moved = false;
      const move = (ev) => {
        if (!moved && Math.hypot(ev.clientX - sx, ev.clientY - sy) < 5) return;
        if (!moved) {
          moved = true;
          S.dragging = true;
          select({ kind: 'placement', idx }, true);
          box.classList.add('swapping');
        }
        box.style.transform = `translate(${ev.clientX - sx}px, ${ev.clientY - sy}px)`;
      };
      const up = (ev) => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        box.style.transform = '';
        box.classList.remove('swapping');
        if (!moved) { select({ kind: 'placement', idx }); return; }
        S.dragging = false;
        const target = slotIndexAt(ev.clientX, ev.clientY, page);
        if (target !== -1 && target !== idx) {
          const list = page.placements;
          if (target < list.length) {
            [list[idx], list[target]] = [list[target], list[idx]];
          } else {                      // dropped on an empty slot: move there
            list.push(list.splice(idx, 1)[0]);
          }
          reflowSlots(page);
          markDirty();
        }
        renderCanvas(true);
        renderFilm();
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up);
    });
    return finishPlacement(box, pl, idx, multi);
  }

  // Drag to move; a still tap/click just selects.
  box.addEventListener('pointerdown', (e) => {
    if (S.locked || !e.isPrimary || e.target.classList.contains('rs')) return;
    e.preventDefault();
    e.stopPropagation();
    const scale = canvasScale();
    const snap = makeSnap();
    const sx = e.clientX, sy = e.clientY, ox = pl.x_mm, oy = pl.y_mm;
    let moved = false;
    S.dragging = true;
    const move = (ev) => {
      if (S.pinching) return;
      if (!moved && Math.hypot(ev.clientX - sx, ev.clientY - sy) < 4) return;
      if (!moved) { moved = true; select({ kind: 'placement', idx }, true); box.classList.add('sel'); }
      const cx = snap.axis('x', ox + (ev.clientX - sx) / scale + pl.w_mm / 2, TRIM_W / 2);
      const cy = snap.axis('y', oy + (ev.clientY - sy) / scale + pl.h_mm / 2, TRIM_H / 2);
      pl.x_mm = clamp(cx - pl.w_mm / 2,
                      -BLEED, Math.max(-BLEED, CANVAS_W - BLEED - pl.w_mm));
      pl.y_mm = clamp(cy - pl.h_mm / 2,
                      -BLEED, Math.max(-BLEED, CANVAS_H - BLEED - pl.h_mm));
      placeRect(box, pl);
      snap.guides(pl.x_mm + pl.w_mm / 2, pl.y_mm + pl.h_mm / 2);
    };
    const up = () => {
      S.dragging = false;
      clearSnapGuides();
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      if (moved) markDirty();
      // A still tap selects — unless something (e.g. type-anywhere on this
      // same tap) already re-rendered and replaced this element.
      else if (box.isConnected) select({ kind: 'placement', idx });
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });

  return finishPlacement(box, pl, idx, multi);
}

/* Corner handles and pinch belong to single-slot pages only: in a grid the
   rectangle is the layout's to decide. */
function finishPlacement(box, pl, idx, multi) {
  if (multi) {
    // A grid slot is fixed, so pinching zooms the photo within it rather
    // than resizing the frame.
    attachPinch(box, {
      getState: () => ({ z: pl.zoom || 1 }),
      apply: (f, _ang, o) => {
        pl.zoom = clamp(o.z * f, 1, 4);
        placeRect(box, pl);
      },
      end: () => { markDirty(); renderCanvas(true); },
    });
    return box;
  }
  if (isSel('placement', idx) && !S.locked) {
    for (const corner of ['nw', 'ne', 'sw', 'se']) {
      const handle = h('div', { class: `rs ${corner}` });
      handle.addEventListener('pointerdown',
        (e) => startPlacementResize(e, box, pl, corner));
      box.append(handle);
    }
  }

  attachPinch(box, {
    getState: () => ({ x: pl.x_mm, y: pl.y_mm, w: pl.w_mm, h: pl.h_mm }),
    apply: (f, _ang, o) => {
      const w = clamp(o.w * f, 20, CANVAS_W);
      const hh = clamp(o.h * f, 20, CANVAS_H);
      pl.x_mm = clamp(o.x + (o.w - w) / 2, -BLEED, Math.max(-BLEED, CANVAS_W - BLEED - w));
      pl.y_mm = clamp(o.y + (o.h - hh) / 2, -BLEED, Math.max(-BLEED, CANVAS_H - BLEED - hh));
      pl.w_mm = w;
      pl.h_mm = hh;
      placeRect(box, pl);
    },
    end: () => { markDirty(); renderSelToolbar(); },
  });
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
    class: 'textbox' + (isSel('text', tb.id) ? ' sel' : '')
      + (tb.y_mm < 18 ? ' flip' : ''),
    'data-id': tb.id,
    style: `left:${pct(tb.x_mm + BLEED, CANVAS_W)};top:${pct(tb.y_mm + BLEED, CANVAS_H)};` +
           `width:${pct(tb.w_mm, CANVAS_W)};min-height:${pct(tb.h_mm, CANVAS_H)};` +
           `font-size:${tb.size_pt * PT_MM * scale}px;text-align:${tb.align};color:${tb.color};` +
           `font-family:${fontStack(tb.font)}` +
           (tb.rotation ? `;transform:rotate(${tb.rotation}deg)` : ''),
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
    if (S.locked || !e.isPrimary) return;
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
    const sx = e.clientX, sy = e.clientY, ow = tb.w_mm;
    const rad = ((tb.rotation || 0) * Math.PI) / 180;
    S.dragging = true;
    const move = (ev) => {
      const d = (ev.clientX - sx) * Math.cos(rad) + (ev.clientY - sy) * Math.sin(rad);
      tb.w_mm = clamp(ow + d / scale2, 20, TRIM_W - SAFE - tb.x_mm);
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

  const rotate = h('div', { class: 'tb-rotate' }, '⟳');
  rotate.addEventListener('pointerdown', (e) => {
    if (S.locked) return;
    e.preventDefault();
    e.stopPropagation();
    startTextRotate(e, box, tb);
  });

  const scaleH = h('div', { class: 'tb-scale' });
  scaleH.addEventListener('pointerdown', (e) => {
    if (S.locked) return;
    e.preventDefault();
    e.stopPropagation();
    startTextScale(e, box, tb);
  });

  box.append(rotate, handle, content, resize, scaleH);

  attachPinch(box, {
    getState: () => ({ size: tb.size_pt, w: tb.w_mm, h: tb.h_mm,
                       x: tb.x_mm, y: tb.y_mm, rot: tb.rotation || 0 }),
    apply: (f, da, o) => {
      const scale = canvasScale();
      tb.size_pt = clamp(Math.round(o.size * f), 4, 144);
      tb.w_mm = clamp(o.w * f, 15, TRIM_W - 2 * SAFE);
      tb.h_mm = Math.max(5, o.h * f);
      tb.x_mm = clamp(o.x + (o.w - tb.w_mm) / 2, SAFE, Math.max(SAFE, TRIM_W - SAFE - tb.w_mm));
      tb.y_mm = clamp(o.y + (o.h - tb.h_mm) / 2, SAFE, Math.max(SAFE, TRIM_H - SAFE - tb.h_mm));
      tb.rotation = normDeg(o.rot + da);
      box.style.left = pct(tb.x_mm + BLEED, CANVAS_W);
      box.style.top = pct(tb.y_mm + BLEED, CANVAS_H);
      box.style.width = pct(tb.w_mm, CANVAS_W);
      box.style.minHeight = pct(tb.h_mm, CANVAS_H);
      box.style.fontSize = `${tb.size_pt * PT_MM * scale}px`;
      box.style.transform = tb.rotation ? `rotate(${tb.rotation}deg)` : '';
    },
    end: () => { markDirty(); renderCanvas(true); renderSelToolbar(); },
  });
  return box;
}

/* Rotate about the box centre; angles are clockwise degrees like CSS.
   Snaps to the compass points within 5°. */
function startTextRotate(e, box, tb) {
  S.dragging = true;
  const r = box.getBoundingClientRect();
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  const start = (Math.atan2(e.clientY - cy, e.clientX - cx) * 180) / Math.PI;
  const orig = tb.rotation || 0;
  const move = (ev) => {
    const a = (Math.atan2(ev.clientY - cy, ev.clientX - cx) * 180) / Math.PI;
    let rot = orig + (a - start);
    rot = ((rot + 180) % 360 + 360) % 360 - 180;
    for (const snapTo of [0, 90, 180, -90, -180]) {
      if (Math.abs(rot - snapTo) < 5) { rot = snapTo === -180 ? 180 : snapTo; break; }
    }
    tb.rotation = Math.round(rot * 10) / 10;
    box.style.transform = tb.rotation ? `rotate(${tb.rotation}deg)` : '';
  };
  const up = () => {
    S.dragging = false;
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    markDirty();
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
}

/* Corner drag scales the font (and the box with it), keeping the centre. */
function startTextScale(e, box, tb) {
  S.dragging = true;
  const r = box.getBoundingClientRect();
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  const d0 = Math.max(8, Math.hypot(e.clientX - cx, e.clientY - cy));
  const o = { size: tb.size_pt, w: tb.w_mm, h: tb.h_mm, x: tb.x_mm, y: tb.y_mm };
  const scale = canvasScale();
  const move = (ev) => {
    const f = clamp(Math.hypot(ev.clientX - cx, ev.clientY - cy) / d0, 0.25, 6);
    tb.size_pt = clamp(Math.round(o.size * f), 4, 144);
    tb.w_mm = clamp(o.w * f, 15, TRIM_W - 2 * SAFE);
    tb.h_mm = Math.max(5, o.h * f);
    tb.x_mm = clamp(o.x + (o.w - tb.w_mm) / 2, SAFE, Math.max(SAFE, TRIM_W - SAFE - tb.w_mm));
    tb.y_mm = clamp(o.y + (o.h - tb.h_mm) / 2, SAFE, Math.max(SAFE, TRIM_H - SAFE - tb.h_mm));
    box.style.left = pct(tb.x_mm + BLEED, CANVAS_W);
    box.style.top = pct(tb.y_mm + BLEED, CANVAS_H);
    box.style.width = pct(tb.w_mm, CANVAS_W);
    box.style.minHeight = pct(tb.h_mm, CANVAS_H);
    box.style.fontSize = `${tb.size_pt * PT_MM * scale}px`;
  };
  const up = () => {
    S.dragging = false;
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    markDirty();
    renderSelToolbar();   // sync the pt select with the new size
  };
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
}

/* Shared text-box move logic; resolves to true if the pointer actually
   dragged (vs a still click). */
function startTextDrag(e, box, tb) {
  return new Promise((resolve) => {
    const scale = canvasScale();
    const snap = makeSnap();
    const sx = e.clientX, sy = e.clientY, ox = tb.x_mm, oy = tb.y_mm;
    let moved = false;
    S.dragging = true;
    const move = (ev) => {
      if (S.pinching) return;
      if (!moved && Math.hypot(ev.clientX - sx, ev.clientY - sy) < 4) return;
      if (!moved) {
        moved = true;
        S.sel = { kind: 'text', id: tb.id };
        highlightSel();
        box.classList.add('sel');
        renderSelToolbar();
      }
      const cx = snap.axis('x', ox + (ev.clientX - sx) / scale + tb.w_mm / 2, TRIM_W / 2);
      const cy = snap.axis('y', oy + (ev.clientY - sy) / scale + tb.h_mm / 2, TRIM_H / 2);
      tb.x_mm = clamp(cx - tb.w_mm / 2,
                      SAFE, Math.max(SAFE, TRIM_W - SAFE - tb.w_mm));
      tb.y_mm = clamp(cy - tb.h_mm / 2,
                      SAFE, Math.max(SAFE, TRIM_H - SAFE - tb.h_mm));
      box.style.left = pct(tb.x_mm + BLEED, CANVAS_W);
      box.style.top = pct(tb.y_mm + BLEED, CANVAS_H);
      snap.guides(tb.x_mm + tb.w_mm / 2, tb.y_mm + tb.h_mm / 2);
    };
    const up = () => {
      S.dragging = false;
      clearSnapGuides();
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

/* Normalize to (-180, 180] and snap within 5° of the compass points. */
function normDeg(rot) {
  rot = ((rot + 180) % 360 + 360) % 360 - 180;
  for (const snapTo of [0, 90, 180, -90, -180]) {
    if (Math.abs(rot - snapTo) < 5) return snapTo === -180 ? 180 : snapTo;
  }
  return Math.round(rot * 10) / 10;
}

/* Two-finger pinch on an element: apply(scaleFactor, angleDelta, startState)
   on every move, end() once. Touch pointers only; single-finger drags check
   S.pinching and stand down while a pinch is active. */
function attachPinch(el, opts) {
  const pts = new Map();
  let base = null;
  const winMove = (e) => {
    if (!pts.has(e.pointerId)) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (base && pts.size >= 2) {
      const [a, b] = [...pts.values()];
      const f = Math.max(0.05, Math.hypot(a.x - b.x, a.y - b.y) / base.d);
      const ang = (Math.atan2(b.y - a.y, b.x - a.x) * 180) / Math.PI;
      opts.apply(f, ang - base.ang, base.state);
    }
  };
  const winUp = (e) => {
    if (!pts.delete(e.pointerId)) return;
    if (base && pts.size < 2) {
      base = null;
      pts.clear();
      S.pinching = false;
      S.dragging = false;
      window.removeEventListener('pointermove', winMove);
      window.removeEventListener('pointerup', winUp);
      window.removeEventListener('pointercancel', winUp);
      opts.end();
    }
  };
  el.addEventListener('pointerdown', (e) => {
    if (S.locked || e.pointerType !== 'touch') return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 2) {
      const [a, b] = [...pts.values()];
      base = {
        d: Math.max(8, Math.hypot(a.x - b.x, a.y - b.y)),
        ang: (Math.atan2(b.y - a.y, b.x - a.x) * 180) / Math.PI,
        state: opts.getState(),
      };
      S.pinching = true;
      S.dragging = true;
      e.preventDefault();
      window.addEventListener('pointermove', winMove);
      window.addEventListener('pointerup', winUp);
      window.addEventListener('pointercancel', winUp);
    }
  });
}

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
  for (const el of document.querySelectorAll('.textbox, .placement, .sticker')) {
    el.classList.remove('sel');
  }
  if (!S.sel) return;
  const el = S.sel.kind === 'placement'
    ? document.querySelector(`.placement[data-idx="${S.sel.idx}"]`)
    : S.sel.kind === 'sticker'
      ? document.querySelector(`.sticker[data-id="${S.sel.id}"]`)
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
    const idx = S.sel.idx || 0;
    const pl = page.placements[idx];
    if (!pl) { bar.classList.add('hidden'); return; }
    if (pageSlots(page).length === 1) {
      // Single-photo page: the two classic framings are layouts of their own.
      const current = pageLayoutId(page);
      bar.append(
        h('button', {
          class: 'btn small' + (current === 'full' ? ' active' : ''),
          onclick: () => applyLayout('full'),
        }, t('tool.fullPage')),
        h('button', {
          class: 'btn small' + (current === 'inset' ? ' active' : ''),
          onclick: () => applyLayout('inset'),
        }, t('tool.inset')),
      );
    }
    if (facingPage(S.page) !== -1) {
      bar.append(h('button', {
        class: 'btn small' + (pl.spread_id ? ' active' : ''),
        onclick: () => (pl.spread_id ? unspanFold(pl) : spanAcrossFold(pl)),
      }, pl.spread_id ? t('tool.unspan') : t('tool.span')));
    }
    if (pl.fit !== 'contain') {
      // Zoom into the framed crop; panning is the ⠿ handle on the photo.
      const zoomBy = (delta) => {
        pl.zoom = clamp(Math.round(((pl.zoom || 1) + delta) * 100) / 100, 1, 4);
        syncSpreadHalf(pl);
        markDirty();
        renderCanvas(true);
      };
      bar.append(
        h('button', {
          class: 'btn small', title: t('tool.zoomOut'),
          disabled: (pl.zoom || 1) <= 1 ? '' : null,
          onclick: () => zoomBy(-0.25),
        }, '−'),
        h('button', {
          class: 'btn small', title: t('tool.zoomIn'),
          onclick: () => zoomBy(0.25),
        }, '+'),
      );
    }
    bar.append(
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
          if (pl.spread_id) unspanFold(pl);   // drop the far half first
          page.placements.splice(idx, 1);
          reflowSlots(page);
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
    for (const f of Object.keys(FONTS)) {
      fontSel.append(h('option', {
        value: f, selected: fontKey(tb.font) === f ? '' : null,
        style: `font-family:${FONTS[f]}`,
      }, FONT_LABELS[f]));
    }
    fontSel.addEventListener('change', () => {
      tb.font = fontSel.value;
      markDirty();
      renderCanvas(true);
    });
    const size = h('select', { 'aria-label': 'Size' });
    const sizes = [9, 11, 14, 18, 24, 32];
    if (!sizes.includes(tb.size_pt)) sizes.push(tb.size_pt);
    for (const v of sizes.sort((a, b) => a - b)) {
      size.append(h('option', { value: v, selected: tb.size_pt === v ? '' : null }, `${v} pt`));
    }
    size.addEventListener('change', () => {
      tb.size_pt = Number(size.value);
      markDirty();
      renderCanvas(true);
    });
    const color = colorControl(tb.color, t('tool.textColor'), (colour) => {
      tb.color = colour;
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
  } else if (S.sel.kind === 'sticker') {
    const list = currentStickerList();
    const st = list.find((x) => x.id === S.sel.id);
    if (!st) { bar.classList.add('hidden'); return; }
    bar.append(h('button', {
      class: 'btn small danger',
      onclick: () => {
        list.splice(list.indexOf(st), 1);
        S.sel = null;
        markDirty();
        renderCanvas(true);
      },
    }, t('tool.remove')));
  } else if (S.sel.kind === 'cover') {
    const cover = S.book.layout.cover;
    const fontSel = h('select', { 'aria-label': 'Font' });
    for (const f of Object.keys(FONTS)) {
      fontSel.append(h('option', {
        value: f, selected: fontKey(cover.title_font) === f ? '' : null,
        style: `font-family:${FONTS[f]}`,
      }, FONT_LABELS[f]));
    }
    fontSel.addEventListener('change', () => {
      cover.title_font = fontSel.value;
      markDirty();
      renderCanvas(true);
    });
    const size = h('select', { 'aria-label': t('tool.titleSize') });
    const sizes = [20, 28, 36];
    if (!sizes.includes(cover.title_size_pt)) sizes.push(cover.title_size_pt);
    for (const v of sizes.sort((a, b) => a - b)) {
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
  if (!S.prices) await loadPrices(); else renderPrices();
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
    if (r.cover_url) {
      grid.append(h('figure', { class: 'pv-page pv-cover' },
        h('img', { src: r.cover_url, alt: t('page.cover') }),
        h('figcaption', {}, t('page.cover'))));
    }
    // Bound, pages face each other: 1 stands alone on the right, then
    // (2,3), (4,5)... and the last page alone on the left. Showing the
    // preview in those pairs is how the book will actually open (A64).
    const figure = (url, i) => h('figure', { class: 'pv-page' },
      h('img', { src: url, alt: `Page ${i + 1}`, loading: 'lazy' }),
      h('figcaption', {}, String(i + 1)));
    const spread = (...kids) => h('div', { class: 'pv-spread' }, ...kids);
    const blank = () => h('div', { class: 'pv-blank' });
    const urls = r.page_urls;
    if (urls.length) grid.append(spread(blank(), figure(urls[0], 0)));
    for (let i = 1; i < urls.length; i += 2) {
      grid.append(i + 1 < urls.length
        ? spread(figure(urls[i], i), figure(urls[i + 1], i + 1))
        : spread(figure(urls[i], i), blank()));
    }
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
      S.page = firstEmptyPage();   // show exactly what is blocking the order
      S.sel = null;
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

/* The simulate button exists only where the dev-config endpoint answers
   (local/dev environments). In production it 404s and the button never
   shows — customers pay by card transfer instead. */
async function ensureDevMode() {
  if (S.devAvailable !== null) return;
  if (window.MEMOBOOK && window.MEMOBOOK.devPaymentSecret) {
    S.devAvailable = true;
    return;
  }
  try {
    const cfg = await api.devConfig();
    S.devAvailable = !!(cfg && cfg.dev_payment_secret);
  } catch (e) {
    S.devAvailable = false;
  }
}

function updateDevButton() {
  if (!S.order) return;
  $('or-dev').classList.toggle('hidden',
    !(S.devAvailable === true && S.order.status === 'pending_payment'));
}

function showOrder() {
  showScreen('order');
  $('or-lookup').classList.add('hidden');
  $('or-details').classList.remove('hidden');
  $('or-ref').textContent = S.order.ref;
  $('or-amount').textContent = fmtAmount(S.order.amount_minor);
  const pending = S.order.status === 'pending_payment';
  $('or-dev').classList.add('hidden');
  ensureDevMode().then(updateDevButton);
  $('or-pay-note').classList.toggle('hidden', !pending);
  renderTimeline(S.order.status);
  updateArtifacts(null);   // until the next poll confirms
  updatePayCard(null);
  pollOrder();
}

/* Card-transfer pilot: while the order is pending, the status payload
   carries the card to transfer to; it replaces the generic pay note. */
function updatePayCard(r) {
  const card = r && r.pay_card;
  $('or-paycard').classList.toggle('hidden', !card);
  if (card) {
    $('or-pay-note').classList.add('hidden');
    const digits = String(card.number).replace(/[^0-9*]/g, '');
    $('pay-number').textContent =
      (digits.match(/.{1,4}/g) || [String(card.number)]).join(' ');
    $('pay-holder').textContent = card.holder || '';
  }
}

/* Dev environments include print-PDF links in the status payload. */
function updateArtifacts(r) {
  const box = $('or-files');
  const urls = r && r.artifact_urls;
  box.classList.toggle('hidden', !urls);
  if (!urls) return;
  $('or-file-interior').classList.toggle('hidden', !urls.interior);
  if (urls.interior) $('or-file-interior').href = urls.interior;
  $('or-file-cover').classList.toggle('hidden', !urls.cover);
  if (urls.cover) $('or-file-cover').href = urls.cover;
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
    updateArtifacts(r);
    if (r.status !== S.order.status) {
      S.order.status = r.status;
      store('mb-order', S.order);
      renderTimeline(r.status);
      updateDevButton();
      $('or-pay-note').classList.toggle('hidden', r.status !== 'pending_payment');
    }
    updatePayCard(r);
  } catch (e) { /* transient */ }
  if (!['delivered', 'cancelled'].includes(S.order.status)) {
    S.orderTimer = setTimeout(pollOrder, 3000);
  }
}

async function devPayNow() {
  const btn = $('or-dev-pay');
  btn.disabled = true;
  let secret = (window.MEMOBOOK && window.MEMOBOOK.devPaymentSecret) || '';
  if (!secret) {
    const cfg = await api.devConfig();   // dev environments: zero typing
    secret = (cfg && cfg.dev_payment_secret) || '';
  }
  if (!secret) secret = (prompt(t('order.devHint')) || '').trim();
  if (!secret) { btn.disabled = false; return; }
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
    renderPrices();
    if (S.book) renderAll();
  });
}

function bind() {
  $('type-grid').addEventListener('click', (e) => {
    const b = e.target.closest('.btype');
    if (b && !b.disabled) pickBookType(b.dataset.btype);
  });
  $('type-change').addEventListener('click', (e) => {
    e.preventDefault();
    showTypeStep();
  });
  $('tier-grid').addEventListener('click', (e) => {
    const b = e.target.closest('.tier');
    // data-tier is sheets of paper; the book is created in pages.
    if (b && !b.disabled) {
      startNewBook(Number(b.dataset.pages || sheetsToPages(Number(b.dataset.tier))));
    }
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
  $('btn-delete-all').addEventListener('click', deleteAllPhotos);
  $('btn-select-mode').addEventListener('click', () => {
    S.selecting = !S.selecting;
    S.selected.clear();
    renderTray();
  });
  $('btn-delete-sel').addEventListener('click', deleteSelectedPhotos);
  $('btn-add-text').addEventListener('click', addTextBox);
  $('btn-add-sticker').addEventListener('click', () => setTrayTab('stickers'));
  $('btn-layout').addEventListener('click', (e) => {
    e.stopPropagation();
    openLayoutPop(e.currentTarget);
  });
  $('tab-photos').addEventListener('click', () => setTrayTab('photos'));
  $('tab-stickers').addEventListener('click', () => setTrayTab('stickers'));
  $('btn-autofill').addEventListener('click', autoFill);
  $('btn-preview').addEventListener('click', openPreview);
  $('tier-select').addEventListener('change', (e) => changeTier(Number(e.target.value)));
  $('btn-view-order').addEventListener('click', () => {
    const saved = load('mb-order');
    if (saved) { S.order = saved; showOrder(); }
  });
  const canvasWrap = $('canvas-wrap');
  canvasWrap.addEventListener('click', (e) => {
    if (e.target.closest('.placement, .textbox, .cover-img, .cover-titles, .sticker, .rs, .tb-handle, .tb-resize, .tb-rotate, .tb-scale')) {
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
  $('pay-copy').addEventListener('click', async () => {
    const digits = $('pay-number').textContent.replace(/\s/g, '');
    try {
      await navigator.clipboard.writeText(digits);
    } catch (e) {
      // Plain-HTTP contexts have no clipboard API.
      const ta = h('textarea', { style: 'position:fixed;opacity:0' }, digits);
      document.body.append(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }
    toast(t('order.copied'));
  });
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
