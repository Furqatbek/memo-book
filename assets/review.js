/* The review form — CR-003-9.
 *
 * One page, one button, one request. The permission checkbox is sent
 * exactly as it is: unticked means unticked, and nothing in this file
 * defaults it, remembers it or infers it from anything else.
 *
 * The photo goes up separately and FIRST, so that a failed upload cannot
 * lose the words somebody has just written.
 */
(function () {
  var script = document.currentScript;
  if (!script) return;
  var token = script.getAttribute('data-token');
  if (!token) return;

  var text = document.getElementById('r-text');
  var name = document.getElementById('r-name');
  var city = document.getElementById('r-city');
  var photo = document.getElementById('r-photo');
  var publish = document.getElementById('r-publish');
  var send = document.getElementById('r-send');
  var status = document.getElementById('r-status');
  var busy = false;

  function say(message) { status.textContent = message; }

  function base() { return '/api/v1/reviews/' + encodeURIComponent(token); }

  function sendPhoto() {
    var file = photo.files && photo.files[0];
    if (!file) return Promise.resolve();
    var form = new FormData();
    form.append('photo', file);
    return fetch(base() + '/photo', {
      method: 'POST', body: form, credentials: 'same-origin',
    }).then(function (r) {
      /* A photo that would not go up must not take the review with it. */
      if (!r.ok) say('The photo did not upload — sending your words anyway.');
    }).catch(function () {
      say('The photo did not upload — sending your words anyway.');
    });
  }

  send.addEventListener('click', function () {
    if (busy) return;
    var written = (text.value || '').trim();
    if (!written) { say('Write something first.'); return; }
    busy = true;
    send.disabled = true;
    say('Sending…');

    sendPhoto().then(function () {
      return fetch(base(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          text: written,
          display_name: (name.value || '').trim() || null,
          city: (city.value || '').trim() || null,
          lang: (document.documentElement.lang || '').slice(0, 8) || null,
          /* Exactly what the box says. Never defaulted, never assumed. */
          may_publish: !!publish.checked,
        }),
      });
    }).then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      say(publish.checked
        ? 'Thank you — we will not change a word of it.'
        : 'Thank you. This stays between us; we will not publish it.');
    }).catch(function () {
      say('That did not send. Try again in a moment.');
      send.disabled = false;
    }).then(function () { busy = false; });
  });
})();
