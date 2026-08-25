#!/usr/bin/env python3
"""What is still fake? — one command, one answer (A81).

    python scripts/launch_check.py            # from backend/, or anywhere

Every placeholder in this product was tracked in prose: a comment here, a
line in a deployment guide there, a paragraph in ASSUMPTIONS. Prose is how
`ADMIN_TOKEN` came to be missing from the production env template, how the
admin lock test came to cover five routes out of eleven, and how
`Effect.ALERT_OPERATOR` sat declared and unexecuted for the life of the state
machine. `PRICES_CONFIRMED` gave exactly one of these blockers a mechanism.
This gives the rest one.

It reads the real files — `deploy/.env` if the machine has one, the site's
own HTML, the shipped defaults — and prints what stands between here and
taking money, with the fix next to each. Exit code 1 while anything is
outstanding, so it can gate a deploy script.

It does NOT check that the numbers are RIGHT. Nothing can: only the printer
knows the spine width and only the founder knows the price. What it checks is
that somebody has been asked, which is the failure mode that actually
happens.
"""
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent

RED, YELLOW, GREEN, DIM, OFF = "\033[31m", "\033[33m", "\033[32m", "\033[2m", "\033[0m"
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    RED = YELLOW = GREEN = DIM = OFF = ""


@dataclass
class Finding:
    ok: bool
    blocking: bool
    what: str
    detail: str
    fix: str


def read_env() -> dict[str, str]:
    """The deployed .env if there is one, else the example, so this says
    something useful on a laptop as well as on the VPS."""
    for candidate in (REPO / "deploy" / ".env", BACKEND / ".env",
                      REPO / "deploy" / ".env.prod.example"):
        if candidate.exists():
            text = candidate.read_text(encoding="utf-8")
            values = dict(re.findall(r"^([A-Z0-9_]+)=(.*)$", text, re.M))
            values["__source__"] = str(candidate.relative_to(REPO))
            return values
    return {"__source__": "(no .env found — using shipped defaults)"}


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def check_prices(env: dict) -> Finding:
    confirmed = truthy(env.get("PRICES_CONFIRMED"))
    return Finding(
        ok=confirmed, blocking=True,
        what="Prices confirmed",
        detail=("the price list is live"
                if confirmed else
                "checkout refuses every order (503 PRICES_NOT_CONFIRMED)"),
        fix="set the four PRICE_MINOR_* values, then PRICES_CONFIRMED=true")


# The numbers the spec invented, which no printer has ever seen.
SPEC_SPINES = {"SPINE_MM_16": "4.0", "SPINE_MM_32": "6.0",
               "SPINE_MM_48": "8.0", "SPINE_MM_96": "14.0"}


def check_spines(env: dict) -> Finding:
    untouched = [k for k, v in SPEC_SPINES.items()
                 if (env.get(k) or v).strip() == v]
    return Finding(
        ok=not untouched, blocking=True,
        what="Spine widths from the printer",
        detail=("measured values are set"
                if not untouched else
                f"{len(untouched)} of 4 still hold the spec's guess "
                f"({', '.join(untouched)})"),
        fix="docs/printer-questions.md Q1 — a wrong spine wraps the cover "
            "art onto the wrong face and wastes the print run")


def check_admin_token(env: dict) -> Finding:
    token = (env.get("ADMIN_TOKEN") or "").strip()
    ok = bool(token) and not token.startswith("CHANGE_ME")
    return Finding(
        ok=ok, blocking=True,
        what="Admin console reachable",
        detail=("a token is set" if ok else
                "ADMIN_TOKEN is empty or a placeholder, so every admin "
                "route answers 404 and the console does not exist"),
        fix="deploy/bootstrap.sh generates one; or set a long random string")


def check_telegram(env: dict) -> Finding:
    ok = bool((env.get("TELEGRAM_BOT_TOKEN") or "").strip()
              and (env.get("TELEGRAM_CHAT_ID") or "").strip())
    return Finding(
        ok=ok, blocking=True,
        what="Telegram to the printer",
        detail=("configured" if ok else
                "paid orders render their print files and nobody is sent "
                "them; failure alerts go nowhere too"),
        fix="deploy/.env, then scripts/telegram_check.py")


def check_pay_card(env: dict) -> Finding:
    number = (env.get("PAY_CARD_NUMBER") or "").replace(" ", "")
    holder = (env.get("PAY_CARD_HOLDER") or "").strip().upper()
    # "8600 0000 0000 0000" — a real Uzcard BIN with nothing behind it.
    # Everything after the first four digits being zero is the tell.
    all_zeros = len(number) > 4 and set(number[4:]) == {"0"}
    fake = (not number or all_zeros
            or holder in {"", "FIRSTNAME LASTNAME", "NAME SURNAME"})
    return Finding(
        ok=not fake, blocking=True,
        what="Card customers pay into",
        detail=("set" if not fake else
                "the order page shows a placeholder card, so a customer who "
                "wants to pay cannot"),
        fix="PAY_CARD_NUMBER and PAY_CARD_HOLDER in deploy/.env")


def check_backups(env: dict) -> Finding:
    repo = (env.get("RESTIC_REPOSITORY") or "").strip()
    on_box = repo.startswith("/") or repo.startswith("local:")
    return Finding(
        ok=bool(repo) and not on_box, blocking=False,
        what="Backups leaving the machine",
        detail=("configured off-box" if repo and not on_box else
                "nothing is backed up" if not repo else
                f"backing up to {repo}, which is this machine"),
        fix="deploy/install-backup.sh, after setting RESTIC_REPOSITORY "
            "somewhere that is not this VPS")


def check_env_is_production(env: dict) -> Finding:
    """`ENV` defaults to "dev", which is the right default for a laptop and
    the wrong one for a public host: it turns the interactive API docs back
    on, and the schema behind them lists every admin route (A82)."""
    value = (env.get("ENV") or "dev").strip().lower()
    return Finding(
        ok=value == "prod", blocking=True,
        what="Running as production",
        detail=("yes" if value == "prod" else
                f"ENV={value or 'unset'}, so /docs and /openapi.json are "
                "public — and the schema names every admin route"),
        fix="ENV=prod in deploy/.env")


SITE_PAGES = ["index.html", "ru/index.html", "uz/index.html",
              "uz-cyrl/index.html", "kaa/index.html"]
PLACEHOLDER_CONTACT = re.compile(r"XXXXXXXX|example\.com|\+998XXX")


def check_site_contacts() -> Finding:
    guilty: dict[str, int] = {}
    for page in SITE_PAGES:
        path = REPO / page
        if not path.exists():
            continue
        hits = PLACEHOLDER_CONTACT.findall(path.read_text(encoding="utf-8"))
        if hits:
            guilty[page] = len(hits)
    return Finding(
        ok=not guilty, blocking=True,
        what="Contact details on the site",
        detail=("real" if not guilty else
                "placeholders render as working links — a visitor who taps "
                "the phone number or Telegram gets a dead end, which reads "
                f"worse than no link ({sum(guilty.values())} across "
                f"{len(guilty)} pages)"),
        fix="replace the tel:, t.me/ and mailto: targets in all five pages")


def check_test_book() -> Finding:
    """Not machine-checkable, and too important to leave off the list."""
    marker = REPO / "docs" / ".test-book-printed"
    ok = marker.exists()
    return Finding(
        ok=ok, blocking=True,
        what="One book printed and inspected",
        detail=("done" if ok else
                "nobody has held one. Every geometry number in this system "
                "is unverified against paper until somebody does"),
        fix="order one, check the spine, the gutter and the trim, then "
            "`touch docs/.test-book-printed`")


def main() -> int:
    env = read_env()
    findings = [
        check_prices(env), check_spines(env), check_admin_token(env),
        check_telegram(env), check_pay_card(env), check_site_contacts(),
        check_env_is_production(env), check_backups(env), check_test_book(),
    ]

    print(f"\n{DIM}config read from {env['__source__']}{OFF}\n")
    width = max(len(f.what) for f in findings)
    for f in findings:
        if f.ok:
            mark, colour = "ok  ", GREEN
        elif f.blocking:
            mark, colour = "STOP", RED
        else:
            mark, colour = "warn", YELLOW
        print(f"  {colour}{mark}{OFF}  {f.what.ljust(width)}  {f.detail}")
        if not f.ok:
            print(f"        {' ' * width}  {DIM}→ {f.fix}{OFF}")

    blockers = [f for f in findings if not f.ok and f.blocking]
    warnings = [f for f in findings if not f.ok and not f.blocking]
    print()
    if blockers:
        print(f"{RED}{len(blockers)} thing(s) between here and taking "
              f"money.{OFF}")
    elif warnings:
        print(f"{YELLOW}Ready to sell, with {len(warnings)} thing(s) worth "
              f"doing.{OFF}")
    else:
        print(f"{GREEN}Nothing left on this list.{OFF}")
    print()
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
