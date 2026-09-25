#!/usr/bin/env node
/* Run the browser checks against a locally running dev server.
 *
 *   cd backend && python scripts/devserver.py     # in one terminal
 *   cd browser-tests && npm install && node run.js
 *
 *   node run.js e2e admincheck     # just these
 *   node run.js --list
 *
 * Each check is an independent script that drives a real browser and prints
 * what it saw. They exist because the editor and the admin console have no
 * other automated coverage: the backend suite proves the API and the print
 * files are right, and these prove the pages that produce them are.
 */
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const CHECKS = path.join(__dirname, 'checks');
const BASE = process.env.MB_BASE || 'http://127.0.0.1:8000';

/* Checks left out of a plain `node run.js`, because they need a server or a
   setting the rest of the suite cannot share. Ask for one by name to run it.
   Each entry says what it wants, so nobody has to read this file to find out. */
const SOLO = {
  campaign: 'a dev server started with CAMPAIGN_DEADLINE, CAMPAIGN_LABEL and '
    + 'PRODUCTION_DAYS set — no other check wants a countdown on the screen. '
    + '`CAMPAIGN_DEADLINE=2099-12-31 CAMPAIGN_LABEL="New Year" '
    + 'PRODUCTION_DAYS=14 python scripts/devserver.py`',
  sitecheck: 'the marketing site on :8090 — `python -m http.server 8090` '
    + 'from the repo root',
  pricegate: 'PRICES_CONFIRMED=false, which stops every other check that '
    + 'reaches checkout',
  shots: 'nothing — but it is a camera, not a check: it walks the whole '
    + 'flow twice and asserts nothing. `node checks/shots.js <tag>`',
  langshots: 'nothing — also a camera: the first screen in all five '
    + 'languages, for looking at the display face. `node checks/langshots.js`',
};
// Checks that need a specific server configuration to mean anything.
const NEEDS = {
  pricegate: 'PRICES_CONFIRMED=false (the dev server sets it true)',
  admincheck: 'ADMIN_TOKEN=dev-admin (the dev server sets this by default)',
  adminwiring: 'ADMIN_TOKEN=dev-admin (it drives the console as an operator)',
  attention: 'ADMIN_TOKEN=dev-admin (it signs into the console)',
  // These two seed their own catalogue through the admin API rather than
  // depending on designs someone uploaded by hand.
  designflow: 'ADMIN_TOKEN=dev-admin (it seeds its own cover designs)',
  designswap: 'ADMIN_TOKEN=dev-admin (it seeds its own cover designs)',
  backart: 'ADMIN_TOKEN=dev-admin (it seeds a design, then adds a back to it '
    + 'through the console)',
  tglink: 'ADMIN_TOKEN=dev-admin and TELEGRAM_WEBHOOK_SECRET (the dev server '
    + 'sets both; it drives the console and the bot webhook against it)',
  urlrefresh: 'nothing — but it intercepts every request to fake expired '
    + 'signed URLs, so it is slow and best not run alongside others',
  receipt: 'ADMIN_TOKEN=dev-admin (it checks the operator gets a link to '
    + 'open, not just that the customer was thanked)',
  swatchpop: 'nothing — and it needs no photos either, so it is the fastest '
    + 'check here; it guards the race that made freeform flaky (A101)',
  rawphoto: 'nothing — it uploads fixtures/prorawA.dng, whose real picture '
    + 'hides in a SubIFD behind a 320x240 thumbnail (A103)',
  bookcfg: 'nothing — it makes a "love" book, whose prefilled cover title is '
    + 'the text that used to be impossible to remove (A104)',
  ogtags: 'the dev server serving the site at `/` — it reads the link-preview '
    + 'tags on all five pages and fetches the image they point at (P1-4)',
  reviewslot: 'the dev server serving the site at `/` — it serves its own '
    + 'reviews through a route intercept, because a fixture review living '
    + 'in the repository is an invented review (P1-3)',
  promises: 'the dev server serving the site at `/` — it reads the FAQ and '
    + 'the reprint policy on all five pages (P1-1)',
  trackorder: 'the dev server serving the site at `/` — it follows the '
    + 'Support link from every language page into the order lookup (P0-2)',
  resumebanner: 'the dev server serving the site at `/`, which it now does '
    + 'by default — the front page reads the editor\'s localStorage, so the '
    + 'two have to be one origin (A105)',
  tgremind: 'TELEGRAM_BOT_USERNAME + TELEGRAM_WEBHOOK_SECRET (the dev '
    + 'server sets both) — it takes the deep link out of the editor bar '
    + 'and drives the real /start and /stop through the webhook (Change 2)',
  funnel: 'ADMIN_TOKEN=dev-admin (the dev server sets it) — it clicks an '
    + 'advert link with a campaign on it and builds a book in ONE browser '
    + 'context, then reads the funnel report back to prove the whole '
    + 'journey arrives attributed to that campaign (Change 3)',
  policies: 'the dev server serving the site at `/` — it follows the '
    + 'privacy and terms links out of the footer of all fifteen selling '
    + 'pages rather than building the URLs itself, because a relative href '
    + 'that works from / and not from /ru/new-year/ is the bug (P2-4)',
  pageweight: 'the dev server serving the site at `/`, which does NOT gzip '
    + 'where production Caddy does — so it throttles to a slow 4G cell and '
    + 'measures the pessimistic case (P2-3)',
  landings: 'the dev server serving the site at `/` — it opens all ten '
    + 'campaign landing pages, checks /new-year resolves without its '
    + 'trailing slash (the form that goes in an ad), and that switching '
    + 'language stays on the campaign rather than dropping the visitor on '
    + 'the home page (P2-1)',
  delivery: 'the dev server serving the site at `/` — it opens the delivery '
    + 'FAQ entry on all five pages and reads the answer after expanding it, '
    + 'because a <details> that opens onto nothing looks fine in the source '
    + '(P1-6)',
  editorlang: 'nothing — it switches language three uploads into a book and '
    + 'checks the book survives it, which is why the control was worth '
    + 'adding to the editor bar rather than leaving on the start screen',
  ordertoast: 'nothing — it strips the EXIF out of the jpg fixtures itself, '
    + 'which is what Telegram and WhatsApp do to a photo on the way through, '
    + 'and that book is placed in upload order (P1-5)',
  autoflow: 'AUTO_CONFIRM_ORDERS=true',
  ordersadmin: 'AUTO_CONFIRM_ORDERS=false — the opposite of autoflow, so the '
    + 'two cannot pass in the same run',
  paycard: 'PAY_CARD_NUMBER + PAY_CARD_HOLDER',
  growth: 'nothing — it drives the share link and the contributor link in '
    + 'THREE separate browser contexts, because an owner, a share viewer '
    + 'and a contributor sharing one cookie jar prove nothing about what '
    + 'each of them can actually reach (CR-003)',
};

// autoflow needs auto-confirm ON and ordersadmin needs it OFF: they test the
// two halves of the same decision. Run one pass each way.
const CONFLICTS = [['autoflow', 'ordersadmin']];

const all = fs.readdirSync(CHECKS)
  // `_name.js` is shared code for the checks, not a check (A102).
  .filter((f) => f.endsWith('.js') && !f.startsWith('_'))
  .map((f) => f.replace(/\.js$/, ''))
  .sort();

const args = process.argv.slice(2);
if (args.includes('--list')) {
  for (const name of all) {
    const note = NEEDS[name] ? `   (needs ${NEEDS[name]})` : '';
    console.log(`  ${name}${SOLO[name] ? '  [not in a default run]' : ''}${note}`);
  }
  console.log('\nRun on their own, because they need something the rest cannot share:');
  for (const [name, why] of Object.entries(SOLO)) console.log(`  ${name} — needs ${why}`);
  process.exit(0);
}

const wanted = args.length ? args : all.filter((n) => !SOLO[n]);

function reachable(url) {
  return new Promise((resolve) => {
    const req = http.get(`${url}/health`, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.setTimeout(2500, () => { req.destroy(); resolve(false); });
  });
}

(async () => {
  if (!await reachable(BASE)) {
    console.error(`No dev server at ${BASE}.`);
    console.error('Start one:  cd backend && python scripts/devserver.py');
    process.exit(2);
  }
  fs.mkdirSync(path.join(__dirname, 'shots'), { recursive: true });

  const failed = [];
  for (const name of wanted) {
    const file = path.join(CHECKS, `${name}.js`);
    if (!fs.existsSync(file)) {
      console.error(`no such check: ${name}`);
      failed.push(name);
      continue;
    }
    process.stdout.write(`${name.padEnd(16)}`);
    try {
      const out = execFileSync('node', [file], { encoding: 'utf8' })
        .split('\n').filter((l) => l && !l.startsWith('[net]'));
      console.log(out[out.length - 1] || 'ok');
    } catch (err) {
      const full = `${err.stdout || ''}${err.stderr || ''}`;
      const detail = full.split('\n').find((l) => /error|failed/i.test(l))
        || 'failed';
      // Keep ALL of it. One matched line is enough to see THAT a check
      // failed and never enough to see why, and a check that only fails
      // inside a full run cannot be re-run on its own to find out — which
      // is how a flake survives for months (A101).
      const log = path.join(__dirname, 'shots', `${name}.fail.log`);
      try { fs.writeFileSync(log, full); } catch { /* best effort */ }
      console.log(`FAILED  ${detail.slice(0, 100)}`);
      console.log(`${' '.repeat(16)}full output: browser-tests/shots/${name}.fail.log`);
      if (NEEDS[name]) console.log(`${' '.repeat(16)}(needs ${NEEDS[name]})`);
      failed.push(name);
    }
  }

  for (const pair of CONFLICTS) {
    if (pair.every((n) => wanted.includes(n)) && pair.some((n) => failed.includes(n))) {
      console.log(`\nNote: ${pair.join(' and ')} need opposite server settings, `
        + 'so at most one of them can pass in a single run.');
    }
  }
  console.log(`\n${wanted.length - failed.length}/${wanted.length} passed`);
  if (failed.length) {
    console.log(`failed: ${failed.join(', ')}`);
    console.log('Run one on its own to see everything it printed:');
    console.log(`  node checks/${failed[0]}.js`);
    process.exit(1);
  }
})();
