# Browser checks

The backend suite proves the API and the print files are right. These prove
the pages that produce them are: the editor and the admin console have no
other automated coverage, and both are plain ES-module apps with no build
step, so a real browser is the only honest way to test them.

Each check is an independent script that drives Chromium and **prints what it
saw**, then exits non-zero if something is wrong. The printout is the point —
when one fails you can usually tell why from the numbers alone.

## Running them

```bash
# one terminal: the dev server (in-process S3, SQLite, eager jobs)
cd backend && python scripts/devserver.py

# another: the checks
cd browser-tests
npm install
node run.js                 # all of them
node run.js e2e admincheck  # just these
node run.js --list          # what exists, and what each one needs
```

Chromium comes from `PLAYWRIGHT_BROWSERS_PATH` if it is set; otherwise
`npx playwright install chromium` once.

## What needs configuring

Most checks run against a plain `python scripts/devserver.py`. A few want more,
because they test behaviour that only exists when it is switched on:

| Check | Needs |
|---|---|
| `admincheck` | `ADMIN_TOKEN` — the dev server sets `dev-admin` by default |
| `adminwiring` | `ADMIN_TOKEN` — it signs into the console and drives every control |
| `startflow` | nothing — the screens before the editor and the checkout summary |
| `attention` | `ADMIN_TOKEN` — it checks what the console shows when orders are stuck |
| `designflow`, `designswap` | `ADMIN_TOKEN` — they seed their own cover designs through the admin API |
| `autoflow` | `AUTO_CONFIRM_ORDERS=true` |
| `ordersadmin` | `AUTO_CONFIRM_ORDERS=false` |
| `paycard` | `PAY_CARD_NUMBER`, `PAY_CARD_HOLDER` |
| `pricegate` | `PRICES_CONFIRMED=false` |

**`autoflow` and `ordersadmin` need opposite settings** — they test the two
halves of the same decision, so at most one can pass per run. Do a pass each
way:

```bash
# pass 1 — trust-first checkout (what production runs)
AUTO_CONFIRM_ORDERS=true PAY_CARD_NUMBER=8600123456789012 \
  PAY_CARD_HOLDER="NAME SURNAME" python scripts/devserver.py
cd browser-tests && node run.js

# pass 2 — orders that wait for the operator to confirm the transfer
AUTO_CONFIRM_ORDERS=false PAY_CARD_NUMBER=8600123456789012 \
  PAY_CARD_HOLDER="NAME SURNAME" python scripts/devserver.py
cd browser-tests && node run.js ordersadmin
```

Two checks are left out of a plain `node run.js` because they need something
the rest of the suite cannot share. Ask for them by name:

- **`sitecheck`** needs the marketing site on `:8090`
  (`python -m http.server 8090` from the repo root).
- **`pricegate`** needs `PRICES_CONFIRMED=false` (A74), which stops every
  other check that reaches checkout — so it gets a server of its own:

  ```bash
  PRICES_CONFIRMED=false python scripts/devserver.py
  cd browser-tests && node run.js pricegate
  ```

`node run.js --list` prints all of this without opening this file.

## Writing one

Copy the shape of an existing check:

- drive the real UI, not internals — click what a customer clicks
- `console.log` the values you assert on, so a failure explains itself
- collect `pageerror` and `console` errors and fail on them at the end
- end with a single `... CHECK PASSED` line; the runner prints the last line

Two traps this codebase has hit repeatedly:

- **`page.waitForFunction(fn, { timeout })` silently ignores that timeout.**
  The second positional argument is `arg`, not options — pass
  `waitForFunction(fn, undefined, { timeout })`.

  This one bit twice. The note above used to claim it was "avoided in every
  check here"; it was not — 29 calls across nine files were still passing
  options into the `arg` slot and silently taking Playwright's 30-second
  default, including ones written to allow 120, 180 and 300 seconds. They
  all pass on an idle machine, which is exactly why nobody noticed: the
  failure only appears when the box is busy, and then it looks like a
  product bug rather than a test bug. All 29 are fixed. If you add a check,
  grep for `waitForFunction(` with a two-argument call before you trust it.
- **A selector may match something a previous run left behind.** Wait for the
  new state (`:not(.retired)`, a changed name), not merely for a matching
  element to exist.

## Screenshots

Checks write to `shots/`, which is gitignored. They are for looking at when
something is wrong, not for comparing automatically — pixel-diffing a page
with real photos in it produces noise, not signal.
