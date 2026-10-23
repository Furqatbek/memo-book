/* "You already have a book" on the front page (A105).

   The editor has always had a resume card on its own start screen, but you
   only saw it after deciding to open the editor. Somebody who left a book
   half-finished and came back to the site was met by "Create your book" and
   nothing else — the same page a first-time visitor sees. Their book was
   safe, sitting in this browser's localStorage, and the site gave them no
   reason to believe it.

   Three things this is careful about:

   * It ASKS THE SERVER before promising anything. A book expires, and the
     credentials outlive it; a banner offering to continue something that is
     gone is worse than no banner. A failed check leaves the banner hidden
     and clears the dead credentials, exactly as the editor does.
   * It only offers to CONTINUE a book that can still be edited. Once an
     order is placed the book is locked, and "continue where you left off"
     would be an invitation to a screen that no longer takes changes.
   * It says WHERE the book is. Nothing about it is on an account — it lives
     in this browser, and somebody who opens the site on their phone will
     find nothing. Better to say so here than to let them discover it.

   The site and the API are the same origin in every deployment (Caddy
   serves the site at `/` and the API under `/api` on the same host), which
   is the same reason the language choice can be shared with the editor. */
(function () {
  var script = document.currentScript;
  if (!script) return;
  var banner = document.getElementById('resume-banner');
  if (!banner) return;
  /* The language pages sit one level down, so they reach the editor as
     `../editor/` — the same arrangement `lang.js` uses for its roots. */
  var editorPath = script.getAttribute('data-editor') || 'editor/';

  function read(key) {
    try { return JSON.parse(localStorage.getItem(key)); } catch (e) { return null; }
  }

  /* ---- an order already placed (A105) ----------------------------------
     Shown until the order is finished, and then not: a banner that goes on
     asking after the book has arrived is a nag, not a service.

     It does NOT repeat the status in words. The order screen already says
     that, in five languages, and putting a second copy of the vocabulary in
     five static HTML files is two places that have to agree about what
     "sent_to_production" is called. The status is fetched to decide whether
     there is anything left to track, and the screen built for it says the
     rest.

     Checked ONCE PER SESSION rather than per page load. The status endpoint
     takes the customer's phone in the query string, and a phone number
     written into the access log on every visit to the front page is a real
     cost for an answer that changes a few times a week. */
  var ORDER_FINISHED = { delivered: 1, cancelled: 1, refunded: 1 };
  var SEEN_KEY = 'sb-order-seen';

  function showOrderRow(order) {
    var row = document.getElementById('order-row');
    if (!row) return;
    var ref = document.getElementById('order-ref');
    if (ref) ref.textContent = order.ref;
    var link = document.getElementById('order-link');
    if (link) link.setAttribute('href', editorPath + '#order');
    row.hidden = false;
    banner.hidden = false;
  }

  var order = read('mb-order');
  if (order && order.ref && order.phone) {
    var asked = null;
    try { asked = sessionStorage.getItem(SEEN_KEY); } catch (e) { /* private mode */ }
    if (asked === order.ref) {
      if (!ORDER_FINISHED[order.status]) showOrderRow(order);
    } else {
      fetch('/api/v1/orders/' + encodeURIComponent(order.ref)
            + '?phone=' + encodeURIComponent(order.phone))
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (live) {
          if (!live || !live.status) return;
          order.status = live.status;
          try {
            localStorage.setItem('mb-order', JSON.stringify(order));
            sessionStorage.setItem(SEEN_KEY, order.ref);
          } catch (e) { /* private mode */ }
          if (!ORDER_FINISHED[order.status]) showOrderRow(order);
        })
        .catch(function () { /* offline, or rate-limited: say nothing */ });
    }
  }

  /* A 404 here is NOT allowed to delete anything, unlike the book below.
     The status endpoint answers 404 for a wrong phone exactly as it does
     for an unknown reference (A77), so a 404 is not proof the order is
     gone — and the reference is the customer's only handle on money they
     have already paid. A book that has expired is genuinely gone; an order
     is a record. */

  /* ---- a book still being made ---------------------------------------- */
  var creds = read('mb-book');
  if (!creds || !creds.book_id || !creds.edit_token) return;

  fetch('/api/v1/books/' + encodeURIComponent(creds.book_id), {
    headers: { 'X-Edit-Token': creds.edit_token }
  }).then(function (r) {
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  }).then(function (book) {
    // `draft` is the only editable state; everything past it means an order
    // is already on its way (the editor calls the rest "locked").
    if (!book || book.status !== 'draft') return;

    var info = document.getElementById('resume-info');
    if (info && book.page_count) {
      info.textContent = (info.getAttribute('data-info') || '')
        .replace('{pages}', String(book.page_count));
    }
    var link = document.getElementById('resume-link');
    if (link) link.setAttribute('href', editorPath);
    var row = document.getElementById('resume-row');
    if (row) row.hidden = false;
    banner.hidden = false;
  }).catch(function (err) {
    // 404 means the book expired or was deleted. Anything else — offline,
    // a proxy hiccup — is not proof of that, so only the clear answer is
    // allowed to throw the credentials away.
    if (String(err && err.message) === '404') {
      try { localStorage.removeItem('mb-book'); } catch (e) { /* private mode */ }
    }
  });
})();
