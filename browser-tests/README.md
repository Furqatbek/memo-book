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

Most checks run against a plain `python scripts/devserver.py`. Three want more,
because they test behaviour that only exists when it is switched on:

| Check | Needs |
|---|---|
| `admincheck` | `ADMIN_TOKEN` — the dev server sets `dev-admin` by default |
| `autoflow` | `AUTO_CONFIRM_ORDERS=true` |
| `paycard` | `PAY_CARD_NUMBER`, `PAY_CARD_HOLDER` |

```bash
AUTO_CONFIRM_ORDERS=true PAY_CARD_NUMBER=8600123456789012 \
  PAY_CARD_HOLDER="NAME SURNAME" python scripts/devserver.py
```

`sitecheck` needs the marketing site on `:8090` (`python -m http.server 8090`
from the repo root) and is excluded from a plain `node run.js`.

## Writing one

Copy the shape of an existing check:

- drive the real UI, not internals — click what a customer clicks
- `console.log` the values you assert on, so a failure explains itself
- collect `pageerror` and `console` errors and fail on them at the end
- end with a single `... CHECK PASSED` line; the runner prints the last line

Two traps this codebase has hit repeatedly, both now avoided in every check
here:

- **`page.waitForFunction(fn, { timeout })` silently ignores that timeout.**
  The second positional argument is `arg`, not options — pass
  `waitForFunction(fn, undefined, { timeout })`.
- **A selector may match something a previous run left behind.** Wait for the
  new state (`:not(.retired)`, a changed name), not merely for a matching
  element to exist.

## Screenshots

Checks write to `shots/`, which is gitignored. They are for looking at when
something is wrong, not for comparing automatically — pixel-diffing a page
with real photos in it produces noise, not signal.
