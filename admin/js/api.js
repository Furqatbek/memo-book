/* Admin API client (A72).

   The token lives in localStorage and rides on every request as
   X-Admin-Token. Every failure the server can give us is a 404 — missing
   token, wrong token, admin switched off entirely — so there is exactly one
   thing to tell the user, and it is the same thing in each case. */

function resolveBase() {
  const stored = (() => {
    try { return localStorage.getItem('mb-api'); } catch { return null; }
  })();
  const base = stored ?? (window.MEMOBOOK && window.MEMOBOOK.apiBase) ?? '';
  return base.replace(/\/+$/, '');
}

export const BASE = resolveBase();
const V = '/api/v1/admin';
const KEY = 'mb-admin-token';

export class AdminError extends Error {
  constructor(status, message) {
    super(message || `HTTP ${status}`);
    this.status = status;
  }
}

export function token() {
  try { return localStorage.getItem(KEY) || ''; } catch { return ''; }
}

export function setToken(value) {
  try {
    if (value) localStorage.setItem(KEY, value);
    else localStorage.removeItem(KEY);
  } catch { /* private mode: the session simply will not persist */ }
}

async function request(method, path, { body, form, tokenOverride } = {}) {
  const headers = { 'X-Admin-Token': tokenOverride ?? token() };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let resp;
  try {
    resp = await fetch(BASE + path, {
      method, headers,
      body: form ?? (body === undefined ? undefined : JSON.stringify(body)),
    });
  } catch {
    throw new AdminError(0, 'No connection to the server.');
  }
  let data = null;
  try { data = await resp.json(); } catch { /* empty or non-JSON */ }
  if (!resp.ok) {
    const detail = data && (data.detail || (data.error && data.error.message));
    throw new AdminError(resp.status, detail);
  }
  return data;
}

/* Sign in: the only call that carries a token the caller has not stored yet. */
export const ping = (candidate) =>
  request('GET', `${V}/ping`, { tokenOverride: candidate });

export const listDesigns = () => request('GET', `${V}/cover-designs`);

export function saveDesign(fields, artworkFile, backArtworkFile) {
  const form = new FormData();
  for (const [k, v] of Object.entries(fields)) {
    if (v !== null && v !== undefined) form.append(k, v);
  }
  form.append('artwork', artworkFile);
  // Sent only when there is one to send: an empty part would still read as
  // "a back artwork was supplied" on the server, and the three states —
  // set it, clear it, leave it — have to stay distinguishable (A95).
  if (backArtworkFile) form.append('back_artwork', backArtworkFile);
  return request('POST', `${V}/cover-designs`, { form });
}

export const patchDesign = (id, patch) =>
  request('PATCH', `${V}/cover-designs/${id}`, { body: patch });

/* Back artwork for a design that already exists, without re-uploading the
   front it does not change (A95). */
export function saveBackArtwork(id, file) {
  const form = new FormData();
  form.append('artwork', file);
  return request('POST', `${V}/cover-designs/${id}/back-artwork`, { form });
}

export const retireDesign = (id) =>
  request('DELETE', `${V}/cover-designs/${id}`);

/* ---------- Telegram order control (A97) ----------
   The link code is issued HERE, in the authenticated console, and typed into
   the bot. A code the bot handed out would be visible to everyone in the
   chat, which is the surface the link exists to distrust. */

export const newLinkCode = () => request('POST', `${V}/telegram/link-code`);

export const listOperators = () => request('GET', `${V}/telegram/operators`);

export const revokeOperator = (userId) =>
  request('DELETE', `${V}/telegram/operators/${userId}`);

/* ---------- orders (A73) ---------- */

export function listOrders({ status = 'open', q = '' } = {}) {
  const params = new URLSearchParams();
  params.set('status', status);
  if (q) params.set('q', q);
  return request('GET', `${V}/orders?${params}`);
}

export const getOrder = (ref) =>
  request('GET', `${V}/orders/${encodeURIComponent(ref)}`);

export const confirmPayment = (ref, note) =>
  request('POST', `${V}/orders/${encodeURIComponent(ref)}/confirm-payment`,
          { body: { note: note || null } });

export const setOrderStatus = (ref, target, note) =>
  request('POST', `${V}/orders/${encodeURIComponent(ref)}/status`,
          { body: { target, note: note || null } });

export const resendToPrinter = (ref) =>
  request('POST', `${V}/orders/${encodeURIComponent(ref)}/resend`);

/* Everything stuck, including alerts that never arrived (A76). Not derivable
   from the orders list: a message that failed to reach the printer leaves the
   order looking perfectly healthy. */
export const attention = () => request('GET', `${V}/attention`);
