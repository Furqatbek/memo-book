/* The orders section of the admin console (A73).

   The daily job, in one screen: what came in, whose money arrived, what the
   printer needs, and what to do next. It replaces confirm_payment.py,
   order_status.py and artifacts.py.

   The buttons offered come from `next_statuses`, which the SERVER computes
   from the state machine. Nothing here decides what an order may become —
   if this file and the machine ever disagreed, the machine would refuse and
   the page would be lying about what is possible. */
import * as api from './api.js?v=20260825';

const S = {
  orders: [],
  current: null,     // the loaded detail, or null
  status: 'open',
  query: '',
  busy: false,
  statusesBuilt: false,
};

const $ = (id) => document.getElementById(id);

/* Plain words for a state machine's names. The operator should not have to
   read `sent_to_production` and translate it in their head. */
const STATUS_LABEL = {
  draft_order: 'Not finished',
  pending_payment: 'Waiting for payment',
  paid: 'Paid',
  rendering: 'Preparing print files',
  render_failed: 'Print files failed',
  rendered: 'Ready to print',
  sent_to_production: 'At the printer',
  shipped: 'Shipped',
  delivered: 'Delivered',
  cancelled: 'Cancelled',
  refunded: 'Refunded',
};

/* What a button says, and whether it deserves a confirmation. Anything that
   moves someone's money or is hard to walk back asks first. */
const ACTION = {
  sent_to_production: { label: 'Sent to the printer' },
  shipped: { label: 'Shipped' },
  delivered: { label: 'Delivered' },
  rendering: { label: 'Try the print files again' },
  cancelled: {
    label: 'Cancel order', danger: true,
    confirm: 'Cancel this order?\n\nThe book unlocks so the customer can edit '
      + 'or re-order it. If they already paid, you will need to refund them '
      + 'yourself — this does not move any money.',
  },
  refunded: {
    label: 'Refunded', danger: true,
    confirm: 'Mark this order refunded?\n\nRecord this only after you have '
      + 'actually sent the money back. It does not move any money.',
  },
};

const STATUS_TONE = {
  pending_payment: 'wait', render_failed: 'bad', cancelled: 'off',
  refunded: 'off', delivered: 'good', shipped: 'good', rendered: 'ready',
};

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.className = v;
    else if (k.startsWith('on') && typeof v === 'function') {
      el.addEventListener(k.slice(2).toLowerCase(), v);
    } else if (v !== null && v !== undefined) el.setAttribute(k, v);
  }
  for (const kid of kids) if (kid !== null && kid !== undefined) el.append(kid);
  return el;
}

/* Amounts are integer tiyin and must never become floats on the way to a
   screen — the same rule the backend keeps. */
function money(minor, currency) {
  const whole = Math.round(minor / 100);
  return `${whole.toLocaleString('en-US').replace(/,/g, ' ')} ${currency || 'UZS'}`;
}

function when(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—'
    : d.toLocaleString('en-GB', { day: '2-digit', month: 'short',
                                  hour: '2-digit', minute: '2-digit' });
}

const bytes = (n) => (n > 1e6 ? `${(n / 1e6).toFixed(1)} MB`
  : `${Math.max(1, Math.round(n / 1000))} KB`);

/* ---------- list ---------- */

export async function refreshOrders(deps) {
  try {
    const body = await api.listOrders({ status: S.status, q: S.query });
    S.orders = body.orders || [];
    // The server tells us which statuses exist; the filter is built from
    // that rather than a list here that would drift from the state machine.
    if (body.statuses && !S.statusesBuilt) buildStatusFilter(body.statuses);
  } catch (e) {
    if (e.status === 404) return deps.signOut();
    deps.toast(e.message || 'Could not load orders.', 'warn');
    return;
  }
  renderOrderList(deps);
  await refreshAttention(deps);
}

/* A76. Everything stuck, at the top of the screen the operator already
   opens. Silent when there is nothing — a panel that is always there is a
   panel nobody reads. */
export async function refreshAttention(deps) {
  const panel = $('attention');
  if (!panel) return;
  let body;
  try {
    body = await api.attention();
  } catch (e) {
    // Never let this break the orders list: it is a helper, not the job.
    if (e.status === 404) return;
    return;
  }
  const items = body.items || [];
  panel.classList.toggle('hidden', items.length === 0);
  if (!items.length) return;

  $('attention-count').textContent = items.length === 1
    ? '1 thing needs you'
    : `${items.length} things need you`;

  const list = $('attention-list');
  list.innerHTML = '';
  for (const item of items) {
    const li = document.createElement('li');
    const ref = document.createElement('b');
    ref.textContent = item.human_ref || '—';
    li.append(ref);

    const what = document.createElement('span');
    what.textContent = ` ${item.summary}`;
    li.append(what);

    if (item.action) {
      const action = document.createElement('small');
      action.className = 'muted';
      action.textContent = item.action;
      li.append(action);
    }
    if (item.detail) {
      const detail = document.createElement('small');
      detail.className = 'muted detail';
      detail.textContent = item.detail;
      li.append(detail);
    }
    // Clicking opens the order, which is where every fix lives.
    if (item.human_ref) {
      li.className = 'clickable';
      li.addEventListener('click', () => openOrder(item.human_ref, deps));
    }
    list.append(li);
  }
}

/* "Open" and "All" answer most days; the rest let the operator ask a real
   question — "what is at the printer right now". */
function buildStatusFilter(statuses) {
  const select = $('o-status');
  for (const value of statuses) {
    if ([...select.options].some((o) => o.value === value)) continue;
    const option = document.createElement('option');
    option.value = value;
    option.textContent = STATUS_LABEL[value] || value;
    select.append(option);
  }
  S.statusesBuilt = true;
}

function renderOrderList(deps) {
  const list = $('order-list');
  list.innerHTML = '';
  $('orders-empty').classList.toggle('hidden', S.orders.length > 0);
  for (const o of S.orders) {
    const row = h('button', {
      class: 'order-row' + (S.current && S.current.human_ref === o.human_ref
        ? ' active' : ''),
      type: 'button', 'data-ref': o.human_ref,
      onclick: () => openOrder(o.human_ref, deps),
    });
    const top = h('span', { class: 'or-top' },
      h('b', {}, o.human_ref),
      h('span', { class: 'muted small' }, money(o.amount_minor, o.currency)));
    const mid = h('span', { class: 'or-mid' }, o.customer_name || '—');
    const bot = h('span', { class: 'or-bot' },
      h('span', { class: `status-pill ${STATUS_TONE[o.status] || ''}` },
        STATUS_LABEL[o.status] || o.status),
      h('span', { class: 'muted small' }, when(o.created_at)));
    row.append(top, mid, bot);
    list.append(row);
  }
}

/* ---------- detail ---------- */

export async function openOrder(ref, deps) {
  try {
    S.current = await api.getOrder(ref);
  } catch (e) {
    return deps.adminError(e, `Could not load ${ref}.`);
  }
  renderDetail(deps);
  renderOrderList(deps);
}

function renderDetail(deps) {
  const o = S.current;
  $('order-empty').classList.add('hidden');
  $('order-detail').classList.remove('hidden');

  $('od-ref').textContent = o.human_ref;
  const pill = $('od-status');
  pill.textContent = STATUS_LABEL[o.status] || o.status;
  pill.className = `status-pill ${STATUS_TONE[o.status] || ''}`;
  $('od-amount').textContent = money(o.amount_minor, o.currency);
  $('od-book').textContent = [
    o.page_count ? `${o.page_count / 2} sheets (${o.page_count} pages)` : null,
    o.book_type,
  ].filter(Boolean).join(' · ');

  $('od-name').textContent = o.customer_name || '—';
  $('od-phone').textContent = o.customer_phone || '—';
  $('od-email').textContent = o.customer_email || '—';
  $('od-address').textContent = o.customer_address || '—';

  // The one thing that needs saying loudly, if anything does.
  const alert = $('od-alert');
  alert.classList.add('hidden');
  if (o.status === 'pending_payment') {
    alert.textContent = 'Waiting for the card transfer. Confirm it below once '
      + 'you see the money — that starts the print files.';
    alert.classList.remove('hidden');
  } else if (o.status === 'render_failed') {
    alert.textContent = 'The print files could not be made. Try again; if it '
      + 'keeps failing the book itself is the problem, not the printer.';
    alert.classList.remove('hidden');
  }

  // Low-resolution placements, above the files rather than below them: it
  // is worth reading before the PDFs are opened, not after (A79).
  const soft = o.soft_pages || [];
  const softEl = $('od-soft');
  softEl.classList.toggle('hidden', soft.length === 0);
  if (soft.length) {
    const worst = soft.some((s) => s.status === 'block')
      ? 'will print blurry' : 'will print soft';
    const where = soft.slice(0, 8).map((s) => s.where).join(', ')
      + (soft.length > 8 ? ` (+${soft.length - 8} more)` : '');
    softEl.textContent = `Low resolution: ${where} ${worst}. `
      + 'The customer saw this warning and confirmed.';
  }

  const files = $('od-files');
  files.innerHTML = '';
  $('od-nofiles').classList.toggle('hidden', o.artifacts.length > 0);
  for (const a of o.artifacts) {
    files.append(h('a', {
      class: 'btn small', href: a.url, target: '_blank', rel: 'noopener',
    }, `${a.kind === 'cover' ? 'Cover' : 'Interior'} PDF · ${bytes(a.bytes)}`));
  }
  $('btn-resend').classList.toggle('hidden', o.artifacts.length === 0);

  renderActions(deps);

  const events = $('od-events');
  events.innerHTML = '';
  for (const e of o.events) {
    events.append(h('li', {},
      h('span', { class: 'ev-when muted small' }, when(e.at)),
      h('span', {}, `${STATUS_LABEL[e.to] || e.to}`),
      e.note ? h('span', { class: 'muted small' }, `— ${e.note}`) : null));
  }
}

function renderActions(deps) {
  const o = S.current;
  const box = $('od-actions');
  box.innerHTML = '';

  if (o.status === 'pending_payment') {
    box.append(h('button', {
      class: 'btn primary', type: 'button',
      onclick: () => act(deps, 'confirm'),
    }, 'The transfer arrived — mark paid'));
  }

  for (const target of o.next_statuses) {
    const spec = ACTION[target];
    if (!spec) continue;
    box.append(h('button', {
      class: `btn${spec.danger ? ' danger' : ''}`, type: 'button',
      'data-target': target,
      onclick: () => act(deps, target, spec),
    }, spec.label));
  }

  if (!box.children.length) {
    box.append(h('span', { class: 'muted small' },
      'Nothing to do — this order is finished.'));
  }
}

async function act(deps, what, spec) {
  if (S.busy) return;
  if (spec && spec.confirm && !confirm(spec.confirm)) return;
  const note = $('od-note').value.trim();
  const ref = S.current.human_ref;
  S.busy = true;
  for (const b of $('od-actions').querySelectorAll('button')) b.disabled = true;
  try {
    if (what === 'confirm') {
      const body = await api.confirmPayment(ref, note);
      S.current = body;
      deps.toast(body.already
        ? `${ref} was already paid — nothing changed.`
        : `${ref} marked paid. Print files are being made.`);
    } else {
      S.current = await api.setOrderStatus(ref, what, note);
      deps.toast(`${ref}: ${STATUS_LABEL[what] || what}.`);
    }
    $('od-note').value = '';
    renderDetail(deps);
    await refreshOrders(deps);
  } catch (e) {
    await deps.adminError(e, 'That did not work.');
    renderActions(deps);
  } finally {
    S.busy = false;
  }
}

async function resend(deps) {
  const ref = S.current && S.current.human_ref;
  if (!ref) return;
  try {
    S.current = await api.resendToPrinter(ref);
    deps.toast(`Production message queued again for ${ref}.`);
    renderDetail(deps);
  } catch (e) {
    await deps.adminError(e, 'Could not send it again.');
  }
}

/* ---------- wiring ---------- */

export function bindOrders(deps) {
  $('btn-orders-refresh').addEventListener('click', () => refreshOrders(deps));
  $('btn-attention-refresh').addEventListener('click',
    () => refreshAttention(deps));
  $('btn-resend').addEventListener('click', () => resend(deps));
  $('o-status').addEventListener('change', (e) => {
    S.status = e.target.value;
    refreshOrders(deps);
  });
  let timer = null;
  $('o-search').addEventListener('input', (e) => {
    S.query = e.target.value.trim();
    clearTimeout(timer);
    // Typing a reference should not fire a request per keystroke.
    timer = setTimeout(() => refreshOrders(deps), 250);
  });
}

export function resetOrders() {
  S.orders = [];
  S.current = null;
  S.status = 'open';
  S.query = '';
}
