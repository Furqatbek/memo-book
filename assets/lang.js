/* Language handling:
   1. Clicking any language link stores that choice (localStorage) — an
      explicit choice always beats device-language detection.
   2. On the root (English) page only, first visit in a session: redirect to
      the stored language, or failing that the device language, if it maps to
      a version we have. Once per session, so the back button still works.
   Without JavaScript the site simply stays on whatever page was opened. */
(function () {
  var script = document.currentScript;
  if (!script) return;
  var pageLang = (script.getAttribute('data-page-lang') || 'en').toLowerCase();
  var root = script.getAttribute('data-root') || '';
  var PATHS = { en: '', ru: 'ru/', uz: 'uz/', 'uz-cyrl': 'uz-cyrl/', kaa: 'kaa/' };
  var KEY = 'sb-lang';

  function norm(tag) {
    tag = String(tag || '').toLowerCase();
    if (tag.indexOf('kaa') === 0) return 'kaa';
    if (tag.indexOf('uz') === 0) return tag.indexOf('cyrl') !== -1 ? 'uz-cyrl' : 'uz';
    if (tag.indexOf('ru') === 0) return 'ru';
    if (tag.indexOf('en') === 0) return 'en';
    return null;
  }

  document.addEventListener('click', function (e) {
    var a = e.target && e.target.closest && e.target.closest('a[hreflang], a[lang]');
    if (!a) return;
    var lang = norm(a.getAttribute('hreflang') || a.getAttribute('lang'));
    if (lang && PATHS[lang] !== undefined) {
      try { localStorage.setItem(KEY, lang); } catch (err) {}
    }
  });

  if (script.getAttribute('data-entry') !== 'root') return;

  var target = null;
  try { target = norm(localStorage.getItem(KEY)); } catch (err) {}
  if (!target) {
    var cands = navigator.languages || [navigator.language || ''];
    for (var i = 0; i < cands.length; i++) {
      var l = norm(cands[i]);
      if (l) { target = l; break; }
    }
  }
  if (!target || target === pageLang || PATHS[target] === undefined) return;
  try {
    if (sessionStorage.getItem('sb-autoredir')) return;
    sessionStorage.setItem('sb-autoredir', '1');
  } catch (err) { return; }
  location.replace(root + PATHS[target]);
})();
