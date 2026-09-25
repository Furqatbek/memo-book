/* API client. Thin fetch wrapper over the backend contract (backend/API.md):
   X-Edit-Token auth, If-Match concurrency, one error envelope. */

function resolveBase() {
  const param = new URLSearchParams(location.search).get('api');
  if (param !== null) {
    try {
      if (param) localStorage.setItem('mb-api', param.replace(/\/+$/, ''));
      else localStorage.removeItem('mb-api');
    } catch (e) { /* private mode */ }
  }
  let stored = null;
  try { stored = localStorage.getItem('mb-api'); } catch (e) { /* private mode */ }
  const base = stored ?? (window.MEMOBOOK && window.MEMOBOOK.apiBase) ?? '';
  return base.replace(/\/+$/, '');
}

export const BASE = resolveBase();

export class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message || code || `HTTP ${status}`);
    this.status = status;
    this.code = code || 'UNKNOWN';
    this.details = details || {};
  }
}

async function request(method, path, { token, ifMatch, body, signature } = {}) {
  const headers = {};
  if (token) headers['X-Edit-Token'] = token;
  if (ifMatch !== undefined) headers['If-Match'] = String(ifMatch);
  if (signature) headers['X-Dev-Signature'] = signature;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let resp;
  try {
    resp = await fetch(BASE + path, {
      method, headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    throw new ApiError(0, 'NETWORK', null, {});
  }
  if (resp.status === 204) return null;
  let data = null;
  try { data = await resp.json(); } catch (e) { /* non-JSON body */ }
  if (!resp.ok) {
    const err = (data && data.error) || {};
    throw new ApiError(resp.status, err.code, err.message, err.details);
  }
  return data;
}

export async function health() {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 3000);
  try {
    const resp = await fetch(BASE + '/health', { signal: ctrl.signal });
    if (!resp.ok) return false;
    const data = await resp.json();
    return data && data.status === 'ok';
  } catch (e) {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

const V = '/api/v1';

export const prices = () => request('GET', `${V}/prices`, {});

// Ready-made covers for this occasion. Public and bookless: the customer
// chooses one before the book exists, and the filtering is the server's
// job so adding a design needs no frontend deploy (A71).
export const coverDesigns = (bookType) => {
  const q = bookType ? `?book_type=${encodeURIComponent(bookType)}` : '';
  return request('GET', `${V}/cover-designs${q}`, {});
};

export const createBook = (pageCount, bookType) =>
  request('POST', `${V}/books`, {
    body: bookType ? { page_count: pageCount, book_type: bookType }
      : { page_count: pageCount },
  });

export const getBook = (c) =>
  request('GET', `${V}/books/${c.book_id}`, { token: c.edit_token });

export const patchLayout = (c, layout, version) =>
  request('PATCH', `${V}/books/${c.book_id}/layout`,
          { token: c.edit_token, ifMatch: version, body: layout });

export const patchPageCount = (c, pageCount, version) =>
  request('PATCH', `${V}/books/${c.book_id}/page-count`,
          { token: c.edit_token, ifMatch: version, body: { page_count: pageCount } });

export const autoPlace = (c, version) =>
  request('POST', `${V}/books/${c.book_id}/auto-place`,
          { token: c.edit_token, ifMatch: version });

export const eligibility = (c) =>
  request('GET', `${V}/books/${c.book_id}/checkout-eligibility`, { token: c.edit_token });

export const uploadUrl = (c, meta) =>
  request('POST', `${V}/books/${c.book_id}/photos/upload-url`,
          { token: c.edit_token, body: meta });

/* takenAt is the raw EXIF "YYYY:MM:DD HH:MM:SS" read in the browser: the
   downscaled upload carries no EXIF, and date order drives auto-place. */
export const completePhoto = (c, photoId, takenAt) =>
  request('POST', `${V}/books/${c.book_id}/photos/${photoId}/complete`,
          { token: c.edit_token, body: takenAt ? { taken_at_exif: takenAt } : {} });

/* The three things the server cannot see for itself (Change 3): a browser
   opening the editor, moving to the checkout screen, and arriving from a
   reminder. Deliberately NOT routed through `request`: analytics must
   never surface an error to the customer, retry, or hold anything up, so
   this is a bare fire-and-forget that swallows everything. The session and
   the campaign ride on the cookie, so there is nothing to pass. */
export const recordEvent = (type, extra) => {
  try {
    const body = { type, ...(extra || {}) };
    const headers = { 'Content-Type': 'application/json' };
    if (extra && extra.edit_token) {
      headers['X-Edit-Token'] = extra.edit_token;
      delete body.edit_token;
    }
    fetch(`${V}/events`, {
      method: 'POST', headers, body: JSON.stringify(body),
      keepalive: true, credentials: 'same-origin',
    }).catch(() => {});
  } catch (e) { /* never the customer's problem */ }
};

/* The deep link that turns this book into a Telegram conversation. Behind
   the edit token, because minting a recovery secret for somebody else's
   book is exactly what an open endpoint would be used for. */
export const telegramLink = (c) =>
  request('GET', `${V}/books/${c.book_id}/telegram-link`, { token: c.edit_token });

/* The read-only share link (CR-003-1). Minting it is behind the edit
   token; what it produces is not, which is the whole point. */
export const createShare = (c) =>
  request('POST', `${V}/books/${c.book_id}/share`, { token: c.edit_token });

export const revokeShare = (c) =>
  request('DELETE', `${V}/books/${c.book_id}/share`, { token: c.edit_token });

export const listPhotos = (c) =>
  request('GET', `${V}/books/${c.book_id}/photos`, { token: c.edit_token });

export const deletePhoto = (c, photoId) =>
  request('DELETE', `${V}/books/${c.book_id}/photos/${photoId}`, { token: c.edit_token });

export const requestPreview = (c) =>
  request('POST', `${V}/books/${c.book_id}/preview`, { token: c.edit_token });

export const getPreview = (c) =>
  request('GET', `${V}/books/${c.book_id}/preview`, { token: c.edit_token });

export const checkout = (c, form) =>
  request('POST', `${V}/books/${c.book_id}/checkout`, { token: c.edit_token, body: form });

export const orderStatus = (ref, phone) =>
  request('GET', `${V}/orders/${encodeURIComponent(ref)}?phone=${encodeURIComponent(phone)}`);

/* Proof of transfer (A100). Multipart rather than JSON, and the phone rides
   in the BODY rather than the query string — same credential the status
   lookup uses, but a POST has no reason to write a customer's phone number
   into access logs and referrers. */
export async function uploadReceipt(ref, phone, file) {
  const form = new FormData();
  form.append('phone', phone);
  form.append('receipt', file);
  let resp;
  try {
    resp = await fetch(`${BASE}${V}/orders/${encodeURIComponent(ref)}/receipt`,
                       { method: 'POST', body: form });
  } catch (e) {
    throw new ApiError(0, 'NETWORK', null, {});
  }
  let data = null;
  try { data = await resp.json(); } catch (e) { /* non-JSON body */ }
  if (!resp.ok) {
    const err = (data && data.error) || {};
    throw new ApiError(resp.status, err.code, err.message, err.details);
  }
  return data;
}

/* Dev environments only: the API hands over the simulated-payment
   signature (404 in production). */
export const devConfig = () =>
  request('GET', `${V}/payments/dev/config`).catch(() => null);

export const devPay = (ref, amountMinor, secret) =>
  request('POST', `${V}/payments/dev/webhook`, {
    signature: secret,
    body: {
      event_id: `editor-${ref}-${Date.now()}`,
      action: 'pay',
      human_ref: ref,
      amount_minor: amountMinor,
    },
  });

/* Raw PUT of the photo bytes to the presigned URL — storage, not the API. */
export async function putObject(url, file, mime) {
  const resp = await fetch(url, {
    method: 'PUT',
    // The extra header is unsigned and ignored by S3/MinIO; it stops
    // ngrok's free-tier browser interstitial from swallowing the upload
    // when storage is exposed through a tunnel.
    headers: { 'Content-Type': mime, 'ngrok-skip-browser-warning': '1' },
    body: file,
  });
  if (!resp.ok) throw new ApiError(resp.status, 'UPLOAD_FAILED', null, {});
}
