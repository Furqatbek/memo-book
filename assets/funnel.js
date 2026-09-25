/* The top of the funnel (Change 3).
 *
 * The server cannot see somebody reading a marketing page, so this is the
 * one thing the site tells it. Everything further down — a book started, a
 * photo uploaded, a payment — is recorded where the server already knows,
 * precisely because a line like this one can be blocked, lost on a bad
 * connection, or simply never run.
 *
 * The session id and the campaign are NOT sent from here. They live in a
 * first-party cookie the server set on this very request, so the server
 * attributes the visit itself: there is nothing here for a page to get
 * wrong, and nothing worth forging.
 *
 * Once per browsing session. The report counts distinct sessions, so a
 * row per page view would be weight in the table and no extra information.
 */
(function () {
  var KEY = 'mb-visit';
  try {
    if (sessionStorage.getItem(KEY)) return;
    sessionStorage.setItem(KEY, '1');
  } catch (e) {
    /* Private mode: send it and accept the duplicate. Distinct-session
       counting absorbs it, and under-counting a visit is worse. */
  }
  var body = JSON.stringify({ type: 'site_visit' });
  try {
    // keepalive so the request survives the click that leaves the page —
    // a visit recorded only for people who lingered is a biased number.
    fetch('/api/v1/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body,
      keepalive: true,
      credentials: 'same-origin',
    }).catch(function () { /* analytics never interrupts a reader */ });
  } catch (e) { /* ditto */ }
})();
