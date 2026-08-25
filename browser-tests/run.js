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

// Checks that need the marketing site served separately (see README).
const NEEDS_SITE = new Set(['sitecheck']);
// Checks that need a specific server configuration to mean anything.
const NEEDS = {
  admincheck: 'ADMIN_TOKEN=dev-admin (the dev server sets this by default)',
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
    console.log(`  ${name}${note}`);
  }
  process.exit(0);
}

const wanted = args.length ? args : all.filter((n) => !NEEDS_SITE.has(n));

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
