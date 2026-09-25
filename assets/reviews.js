/* Customer reviews (P1-3).
 *
 * THE LIST BELOW IS EMPTY AND THAT IS THE POINT. Until three real customers
 * have said something, the section keeps its honest note: "Verified reviews
 * from our first customers will appear here — the pilot books are being
 * printed right now. We never publish invented quotes." A competitor in
 * this category fills the same space with stock avatars and invented
 * quotes, and it is visible to anyone who looks.
 *
 * TO PUBLISH A REVIEW, add an entry here and drop the photo in
 * `assets/reviews/`. Nothing else changes, and it appears on all five
 * language pages at once.
 *
 *   { name:  'Aziza K.',                  // as they agreed to be named
 *     city:  'Tashkent',                  // optional
 *     photo: 'reviews/aziza.jpg',         // a real photo, theirs or the book's
 *     book:  '64 pages · a year in Samarkand',   // what the book was about
 *     lang:  'ru',                        // the language THEY wrote in
 *     text:  'their own words, untranslated' }
 *
 * Every field except `city` is required. An entry missing one is dropped
 * rather than rendered half-built, because a card with a name and no book
 * is indistinguishable from a card somebody invented in a hurry.
 *
 * THE WORDS ARE NOT TRANSLATED. A review appears in the language it was
 * written in, on every page, with `lang` set so a screen reader says it
 * correctly. Rewriting a customer's sentence into four other languages is
 * putting words in their mouth, which is a smaller version of inventing the
 * quote outright — and the person who left it cannot check what we made
 * them say.
 */
(function () {
  var REVIEWS = [
    // Nothing yet. The pilot books are still being printed.
  ];

  /* Three, because one card in a row built for three does not read as "our
     first customer" — it reads as "one person has ever bought this". The
     honest note is a better thing to show until there are three. Change
     this number if you disagree; nothing else depends on it. */
  var MIN_TO_PUBLISH = 3;

  var script = document.currentScript;
  if (!script) return;
  var grid = document.getElementById('reviews');
  var note = document.querySelector('.reviews-note');
  if (!grid) return;

  // `assets/reviews.js` -> `assets/`, so photo paths are written once and
  // work from the root page and from a language folder alike.
  var base = script.src.replace(/[^/]*$/, '');

  function usable(r) {
    return r && r.name && r.photo && r.book && r.text;
  }

  var ready = REVIEWS.filter(usable);
  if (REVIEWS.length !== ready.length) {
    // Loud, because a dropped review looks exactly like one nobody wrote.
    console.warn('reviews: ' + (REVIEWS.length - ready.length)
      + ' entr(ies) missing a required field were not published');
  }
  if (ready.length < MIN_TO_PUBLISH) return;   // the honest note stays

  ready.forEach(function (r) {
    var card = document.createElement('figure');
    card.className = 'review-card';

    var who = document.createElement('div');
    who.className = 'review-who';

    var img = document.createElement('img');
    img.className = 'review-photo';
    img.src = base + r.photo;
    img.alt = '';                       // the name is right next to it
    img.loading = 'lazy';
    // A missing photo drops the portrait rather than showing a broken icon
    // (A99's lesson, one level down).
    img.addEventListener('error', function () { img.remove(); });

    var meta = document.createElement('div');
    var name = document.createElement('cite');
    name.className = 'review-name';
    name.textContent = r.city ? r.name + ', ' + r.city : r.name;
    var book = document.createElement('span');
    book.className = 'review-book';
    book.textContent = r.book;
    meta.appendChild(name);
    meta.appendChild(book);

    who.appendChild(img);
    who.appendChild(meta);

    var quote = document.createElement('blockquote');
    quote.className = 'review-text';
    quote.textContent = r.text;
    if (r.lang) quote.setAttribute('lang', r.lang);

    card.appendChild(quote);
    card.appendChild(who);
    grid.appendChild(card);
  });

  grid.hidden = false;
  if (note) note.hidden = true;
})();
