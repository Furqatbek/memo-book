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
  sitecheck: 'the marketing site on :8090 — `python -m http.server 8090` '
    + 'from the repo root',
  pricegate: 'PRICES_CONFIRMED=false, which stops every other check that '
    + 'reaches checkout',
};
// Checks that need a specific server configuration to mean anything.
const NEEDS = {
  pricegate: 'PRICES_CONFIRMED=false (the dev server sets it true)',
  admincheck: 'ADMIN_TOKEN=dev-admin (the dev server sets this by default)',
  adminwiring: 'ADMIN_TOKEN=dev-admin (it drives the console as an operator)',
  // These two seed their own catalogue through the admin API rather than
  // depending on designs someone uploaded by hand.
  designflow: 'ADMIN_TOKEN=dev-admin (it seeds its own cover designs)',
  designswap: 'ADMIN_TOKEN=dev-admin (it seeds its own cover designs)',
  autoflow: 'AUTO_CONFIRM_ORDERS=true',
  ordersadmin: 'AUTO_CONFIRM_ORDERS=false — the opposite of autoflow, so the '
    + 'two cannot pass in the same run',
  paycard: 'PAY_CARD_NUMBER + PAY_CARD_HOLDER',
};

// autoflow needs auto-confirm ON and ordersadmin needs it OFF: they test the
// two halves of the same decision. Run one pass each way.
const CONFLICTS = [['autoflow', 'ordersadmin']];

const all = fs.readdirSync(CHECKS)
  .filter((f) => f.endsWith('.js'))
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
      const detail = `${err.stdout || ''}${err.stderr || ''}`
        .split('\n').find((l) => /error|failed/i.test(l)) || 'failed';
      console.log(`FAILED  ${detail.slice(0, 100)}`);
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
