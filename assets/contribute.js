/* The contributor page — CR-003-6.
 *
 * Somebody who is not the owner, on a phone, who was sent a link by a
 * friend. They will pick several photos at once and then put the phone in
 * their pocket, so: one at a time, never in parallel, with a line of text
 * that always says what is happening and what failed.
 *
 * There is no book on this page. This script holds one token, and the only
 * thing it can do with it is add pictures.
 */
(function () {
  var script = document.currentScript;
  if (!script) return;
  var token = script.getAttribute('data-token');
  if (!token) return;

  var files = document.getElementById('c-files');
  var name = document.getElementById('c-name');
  var status = document.getElementById('c-status');
  var sub = document.getElementById('c-sub');
  var cta = document.getElementById('c-cta');
  var busy = false;

  function say(text) { status.textContent = text; }

  function api(path, body) {
    return fetch('/api/v1/contribute/' + encodeURIComponent(token) + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(body || {}),
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          var message = (data.error && data.error.message)
            || data.detail || 'That did not work.';
          throw new Error(message);
        }
        return data;
      });
    });
  }

  function refresh() {
    fetch('/api/v1/contribute/' + encodeURIComponent(token), {
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        sub.textContent = data.contributed_count + ' added so far'
          + (data.photos_left ? ' · room for ' + data.photos_left + ' more' : '');
      }).catch(function () { /* the count is a nicety, never a blocker */ });
  }

  /* One at a time. A phone on mobile data uploading eight originals in
     parallel finishes none of them, and the failure looks like the page
     being broken rather than the connection being slow. */
  function uploadOne(file) {
    return api('/upload-url', {
      filename: file.name.slice(0, 255),
      mime: file.type || 'image/jpeg',
      bytes: file.size,
      contributor_name: (name.value || '').trim() || null,
    }).then(function (issued) {
      return fetch(issued.upload_url, {
        method: 'PUT',
        headers: { 'Content-Type': file.type || 'image/jpeg' },
        body: file,
      }).then(function (r) {
        if (!r.ok) throw new Error('The upload did not go through.');
        return api('/complete', { photo_id: issued.photo_id });
      });
    });
  }

  files.addEventListener('change', function () {
    if (busy) return;
    var chosen = Array.prototype.slice.call(files.files || []);
    if (!chosen.length) return;
    busy = true;
    files.disabled = true;
    var done = 0;
    var failed = [];

    function next() {
      if (!chosen.length) {
        files.disabled = false;
        files.value = '';
        busy = false;
        say(failed.length
          ? done + ' added. ' + failed.length + ' did not: ' + failed[0]
          : done + ' photo' + (done === 1 ? '' : 's') + ' added — thank you.');
        refresh();
        return;
      }
      var file = chosen.shift();
      say('Adding ' + (done + failed.length + 1) + ' of '
          + (done + failed.length + 1 + chosen.length) + '…');
      uploadOne(file).then(function () { done += 1; })
        .catch(function (e) { failed.push(e.message); })
        .then(next);
    }
    next();
  });

  if (cta) {
    cta.addEventListener('click', function () {
      try {
        fetch('/api/v1/events', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ type: 'contributor_cta_clicked' }),
          keepalive: true,
          credentials: 'same-origin',
        }).catch(function () {});
      } catch (e) { /* never delay the click */ }
    });
  }

  refresh();
})();
