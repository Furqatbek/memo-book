/* The shared book, as a stranger sees it — CR-003-1.
 *
 * Everything on this page belongs to somebody else. The viewer holds one
 * token, it is read-only, and the only thing this script can reach is the
 * JSON of page pictures behind it. There is no edit token here, no contact
 * detail, and nothing to save.
 *
 * Pages are loaded lazily. A shared link lands in a group chat and gets
 * opened on mobile data by people who are in the photographs — pulling
 * thirty page images at once would spend their data before they saw the
 * first one.
 */
(function () {
  var script = document.currentScript;
  if (!script) return;
  var token = script.getAttribute('data-token');
  if (!token) return;

  var pages = document.getElementById('share-pages');
  var sub = document.getElementById('share-sub');
  var cta = document.getElementById('share-cta');

  function note(text) {
    pages.innerHTML = '';
    var p = document.createElement('p');
    p.className = 'share-note';
    p.textContent = text;
    pages.appendChild(p);
  }

  function draw(data) {
    sub.textContent = data.page_count + ' pages';
    pages.innerHTML = '';
    var all = [];
    if (data.cover_url) all.push({ url: data.cover_url, label: 'Cover' });
    (data.pages || []).forEach(function (p) {
      all.push({ url: p.url, label: 'Page ' + (p.index + 1) });
    });
    all.forEach(function (item) {
      var fig = document.createElement('figure');
      fig.className = 'share-page';
      var img = document.createElement('img');
      img.src = item.url;
      img.alt = item.label;
      img.loading = 'lazy';
      img.decoding = 'async';
      /* Reserve the box: these are A5-proportioned pages, and without a
         ratio the whole page jumps as each one lands under the reader's
         thumb. */
      img.width = 1190;
      img.height = 1684;
      img.addEventListener('error', function () { fig.remove(); });
      fig.appendChild(img);
      pages.appendChild(fig);
    });
    if (!all.length) note('This book has no pages yet.');
  }

  note('Loading…');
  fetch('/api/v1/shared/' + encodeURIComponent(token), {
    headers: { Accept: 'application/json' },
  }).then(function (r) {
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  }).then(draw).catch(function () {
    note('This link has expired or was turned off by its owner.');
  });

  /* The CTA is the only thing on this page that goes anywhere. Recorded so
     a share can be told from a search result as a source of new books —
     the server stamps the attribution, this only says it was pressed. */
  if (cta) {
    cta.addEventListener('click', function () {
      try {
        fetch('/api/v1/events', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ type: 'share_cta_clicked' }),
          keepalive: true,
          credentials: 'same-origin',
        }).catch(function () {});
      } catch (e) { /* never delay the click */ }
    });
  }
})();
