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


LANG_DIRS = ["", "ru/", "uz/", "uz-cyrl/", "kaa/"]
# The campaign landing pages (P2-1). Ads point straight at these, so they
# are the pages a stranger is likeliest to see FIRST — every honesty check
# that covers the main pages has to cover them too, and a link preview
# matters more here than anywhere else on the site.
LANDING_SLUGS = ["new-year", "family"]
# The privacy policy and the terms (P2-4). Held to the same honesty checks
# as everything else: a policy page that quietly went stale on a contact
# detail is worse than most pages that do, because it is the page a
# customer reads precisely when they have stopped trusting you.
POLICY_SLUGS = ["privacy", "terms"]
SITE_PAGES = ([f"{d}index.html" for d in LANG_DIRS]
              + [f"{d}{s}/index.html"
                 for s in LANDING_SLUGS + POLICY_SLUGS for d in LANG_DIRS])
PLACEHOLDER_CONTACT = re.compile(r"XXXXXXXX|example\.com|\+998XXX")
# Every way the site offers to be contacted. Absolute targets, so they are
# the same string on all five pages — which is what makes them comparable.
CONTACT_TARGET = re.compile(
    r'href="(tel:[^"]+|mailto:[^"]+|https://t\.me/[^"]+'
    r'|https://[^"]*instagram\.com/[^"]+)"')


def check_site_contacts() -> Finding:
    guilty: dict[str, int] = {}
    targets: dict[str, tuple[str, ...]] = {}
    for page in SITE_PAGES:
        path = REPO / page
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        hits = PLACEHOLDER_CONTACT.findall(text)
        if hits:
            guilty[page] = len(hits)
        targets[page] = tuple(sorted(set(CONTACT_TARGET.findall(text))))

    # Five pages, one set of contacts. Once the placeholders are gone this
    # is the failure that actually happens: a number changed on the English
    # page and nowhere else leaves four pages handing out a dead one — and
    # unlike a placeholder, a stale real number looks entirely convincing.
    agreed = next(iter(targets.values()), ())
    adrift = sorted(p for p, t in targets.items() if t != agreed)

    if guilty:
        detail = ("placeholders render as working links — a visitor who taps "
                  "the phone number or Telegram gets a dead end, which reads "
                  f"worse than no link ({sum(guilty.values())} across "
                  f"{len(guilty)} pages)")
    elif adrift:
        detail = ("the five pages do not agree on how to reach you, so some "
                  "languages are handing out contacts the others have "
                  f"already changed: {', '.join(adrift)}")
    else:
        detail = f"real, and the same on all {len(targets)} pages"

    return Finding(
        ok=not guilty and not adrift, blocking=True,
        what="Contact details on the site",
        detail=detail,
        fix="replace the tel:, t.me/ and mailto: targets in all five pages")


# Claims the product cannot keep. AI enhancement is the one that was
# actually on the site: the FAQ promised we would "improve blurry or muddy
# photos before printing", in all five languages, and nothing in the system
# so much as sharpens a pixel. A customer reads that, uploads their blurry
# photos, gets a blurry book and asks for a free reprint — and is right to.
#
# The words are listed per language because the claim was translated. A
# check that only knew the English one would have found a fifth of it.
#
# EVERY WORD HERE MUST BE WRONG IN ANY SENTENCE. A pattern match cannot read
# a negation, and the first draft of this included "retouch": it then fired
# on the honest replacement copy, which says we do NOT retouch photos. A
# checklist that goes red at a true sentence is a checklist people learn to
# skip. These terms have no innocent use on this site while the feature does
# not exist — even "we don't use AI" would be a sentence worth stopping for,
# because it invites the question the FAQ should simply not raise.
UNSHIPPED_CLAIM = re.compile(
    r"\bAI\b|\bнейросет|искусственн\w+ интеллект"
    r"|sun.?iy intellekt|сунъий интеллект|jasalma intellekt"
    r"|\bupscal",
    re.IGNORECASE)


def check_unshipped_claims() -> Finding:
    """The site must not sell a feature that does not exist.

    Delete this check on the day AI enhancement ships — and not before,
    because until then every sentence it catches is one the product cannot
    honour.
    """
    guilty: dict[str, int] = {}
    for page in SITE_PAGES:
        path = REPO / page
        if not path.exists():
            continue
        hits = UNSHIPPED_CLAIM.findall(path.read_text(encoding="utf-8"))
        if hits:
            guilty[page] = len(hits)
    return Finding(
        ok=not guilty, blocking=True,
        what="Only features that exist are advertised",
        detail=("no unshipped claims" if not guilty else
                "the site promises AI enhancement, which is not in the "
                "product. A customer who relies on it gets a blurry book "
                f"and a reprint we cannot absorb ({sum(guilty.values())} "
                f"across {len(guilty)} pages)"),
        fix="describe the resolution warning the editor really shows, or "
            "ship the feature")


# Services that hand out a face nobody owns. A competitor in this category
# fills its reviews with `i.pravatar.cc` portraits beside invented quotes,
# and it is visible to anyone who looks — which is exactly why it is worth
# a blocking check rather than a good intention (P1-3).
FAKE_FACE = re.compile(
    r"pravatar|ui-avatars|dicebear|gravatar\.com|randomuser\.me"
    r"|placehold(?:er)?\.(?:co|com|it)|source\.unsplash",
    re.IGNORECASE)
# A review photograph is a file we hold, of a customer or their book. A
# remote one is somebody else's picture, and it can change or vanish under
# us after it has been vouched for.
REMOTE_PHOTO = re.compile(r"photo\s*:\s*['\"]https?://", re.IGNORECASE)
REVIEW_SOURCES = ["assets/reviews.js"]


def check_review_honesty() -> Finding:
    """No invented faces, and no photographs we do not hold.

    This cannot check whether a QUOTE is real — nothing can. What it can do
    is make the cheapest way to fake one fail loudly.
    """
    guilty: dict[str, str] = {}
    for page in SITE_PAGES + REVIEW_SOURCES:
        path = REPO / page
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if FAKE_FACE.search(text):
            guilty[page] = "a stock-avatar service"
        elif REMOTE_PHOTO.search(text):
            guilty[page] = "a review photo hosted somewhere else"
    return Finding(
        ok=not guilty, blocking=True,
        what="Reviews are real or absent",
        detail=("no invented faces" if not guilty else
                "; ".join(f"{p}: {why}" for p, why in guilty.items())),
        fix="publish real reviews with photographs we hold, or leave the "
            "section showing its honest note")


# The auto-layout card, per language: the word that names the feature, and
# the word that carries the only claim in it worth making (P1-5).
#
# Auto-layout does not "fill the pages" — anything fills pages. It sorts by
# EXIF `taken_at` and rebuilds the trip in the order it happened (R2, see
# app/domain/ordering.py). That is the difference between this editor and a
# grid, and the copy said nothing about it for five languages at once.
#
# This is a drift guard, not a style rule. Five pages carry the same claim
# and only one of them is read by the person editing it, so the way it fails
# is silently, in the four nobody opened. Rephrase freely — keep the claim.
ORDER_CLAIM = {
    # Matches the card under either name, so renaming it is reported as the
    # claim going missing rather than the card going missing.
    "index.html": (r"auto.?(?:layout|placement)", r"in order|order you took"),
    "ru/index.html": (r"автозаполнени", r"поряд"),
    "uz/index.html": (r"avtomatik joylashtirish", r"tartib"),
    "uz-cyrl/index.html": (r"автоматик жойлаштириш", r"тартиб"),
    "kaa/index.html": (r"avtomatikalıq jaylastırıw", r"tártip|tártib"),
}


def check_order_claim() -> Finding:
    """The feature card names the feature AND says what it does.

    Anchored to the `<h3>` and the paragraph under it, because that card is
    the one place on the page where a reader decides whether this is worth
    an evening. A card that only promises to "fill your pages" is selling a
    grid; the software is doing something better and saying nothing.
    """
    silent: dict[str, str] = {}
    for page, (feature, claim) in ORDER_CLAIM.items():
        path = REPO / page
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        card = re.search(rf"<h3>([^<]*{feature}[^<]*)</h3>\s*<p>([^<]*)</p>",
                         text, re.IGNORECASE)
        if not card:
            silent[page] = "no auto-layout card found"
        elif not re.search(claim, card.group(1) + card.group(2), re.IGNORECASE):
            silent[page] = "the card never mentions chronological order"
    return Finding(
        ok=not silent, blocking=False,
        what="Auto-layout sells the ordering",
        detail=("all five languages" if not silent else
                "; ".join(f"{p}: {why}" for p, why in silent.items())),
        fix="say that one click puts the photos in the order they were "
            "taken — it is the best thing the editor does and the page is "
            "the only place a customer can learn it")


# "We deliver anywhere in Uzbekistan", per language (P1-6).
#
# The coverage question is the one a buyer outside Tashkent asks first, and
# an unanswered one is a closed tab — there is nobody to ask at 11pm. It
# has to be in the FAQ, where somebody looking for it will look, AND in the
# footer, where somebody who never thought to ask still passes it.
#
# It matters most on the Karakalpak page, whose readers are furthest from
# the print shop and likeliest to assume the answer is no.
DELIVERY_CLAIM = {
    "": r"deliver anywhere in Uzbekistan",
    "ru/": r"любую точку Узбекистана",
    "uz/": r"istalgan nuqtasiga yetkazib",
    "uz-cyrl/": r"исталган нуқтасига етказиб",
    "kaa/": r"qálegen jerine jetkerip",
}


def _lang_of(page: str) -> str:
    """The language directory a site page lives under ("" for English)."""
    head = page.split("/")[0]
    return f"{head}/" if f"{head}/" in DELIVERY_CLAIM and head else ""


def check_delivery_claim() -> Finding:
    """Every page says it in the footer; every page with an FAQ says it there.

    Both halves apply where there is somewhere to put them rather than to a
    fixed list of pages. A campaign landing page sends its FAQ traffic to
    the main page, so it is held to the footer alone; a policy page carries
    a plain document footer with no marketing column at all, and pushing
    delivery copy into the privacy policy would be noise in the one
    document a customer reads when they have stopped trusting you.
    """
    silent: dict[str, str] = {}
    for page in SITE_PAGES:
        path = REPO / page
        if not path.exists():
            continue
        claim = DELIVERY_CLAIM[_lang_of(page)]
        head, sep, foot = path.read_text(encoding="utf-8").partition("<footer")
        missing = []
        if 'class="faq-list"' in head and not any(
                re.search(claim, d, re.IGNORECASE) for d in
                re.findall(r"<details>(.*?)</details>", head, re.S)):
            missing.append("not in the FAQ")
        sells = 'class="f-col f-brand"' in foot
        if sells and not re.search(claim, foot, re.IGNORECASE):
            missing.append("not in the footer")
        if missing:
            silent[page] = " and ".join(missing)
    return Finding(
        ok=not silent, blocking=False,
        what="Delivery coverage is stated",
        detail=(f"footer on all {len(SITE_PAGES)} pages, and in every FAQ"
                if not silent else
                "; ".join(f"{p}: {why}" for p, why in silent.items())),
        fix="say that we deliver anywhere in Uzbekistan — a buyer in Nukus "
            "who cannot find that out closes the tab, and nobody ever hears "
            "that they tried")


# P2-3. The audience is on mobile data, and every second of load is paid
# traffic bought and lost. Today the site carries NO raster images at all —
# every illustration is inline SVG and the type is a system stack — so the
# whole site is around 19 KB gzipped and first paint lands well inside the
# three-second target with room to spare.
#
# That is exactly why this check exists now rather than later. Nothing is
# slow yet; the budget is here so that the first real photograph — a
# printed book for the OG card, a customer's review portrait — cannot
# quietly turn a 19 KB page into a 2 MB one. A budget written after the
# regression is a post-mortem.
#
# Raw bytes, not gzipped: Caddy compresses in production, so every number
# here is the pessimistic case, and a budget you cannot game by reaching
# for a better compressor is the one worth having.
PAGE_BUDGET_KB = 120          # html + every local asset it pulls in
IMAGE_BUDGET_KB = 200         # any single raster file a PAGE loads
LOCAL_REF = re.compile(r'(?:src|href)="(?!https?:|//|#|data:|mailto:|tel:)([^"]+)"')
RASTER = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif")


def _page_assets(page: str) -> list[Path]:
    """Local files a page pulls in. Not a browser, so it sees what the
    markup asks for, which is the thing a budget can be held to."""
    path = REPO / page
    base = path.parent
    out = []
    for ref in LOCAL_REF.findall(path.read_text(encoding="utf-8")):
        ref = ref.split("?")[0].split("#")[0]
        if not ref or ref.endswith("/"):
            continue          # a link to another page, not an asset
        target = (base / ref).resolve()
        if target.is_file() and target.suffix in (
                ".css", ".js", ".mjs", ".svg", *RASTER):
            out.append(target)
    return out


def check_page_weight() -> Finding:
    """Every page, with everything it loads, inside the budget."""
    heavy: dict[str, str] = {}
    worst = ("", 0)
    for page in SITE_PAGES:
        if not (REPO / page).exists():
            continue
        assets = _page_assets(page)
        total = (REPO / page).stat().st_size + sum(a.stat().st_size for a in assets)
        if total > worst[1]:
            worst = (page, total)
        if total > PAGE_BUDGET_KB * 1024:
            heavy[page] = f"{total // 1024} KB over the wire uncompressed"
        for a in assets:
            if a.suffix in RASTER and a.stat().st_size > IMAGE_BUDGET_KB * 1024:
                heavy[page] = (f"{a.name} is {a.stat().st_size // 1024} KB")
    return Finding(
        ok=not heavy, blocking=False,
        what="Page weight within budget",
        detail=(f"heaviest is {worst[0] or 'n/a'} at {worst[1] // 1024} KB "
                f"of {PAGE_BUDGET_KB} KB, uncompressed" if not heavy else
                "; ".join(f"{p}: {why}" for p, why in heavy.items())),
        fix=f"keep a page under {PAGE_BUDGET_KB} KB and any single image "
            f"under {IMAGE_BUDGET_KB} KB — the audience is on mobile data, "
            "and a slow page is paid traffic bought and thrown away")


# Any <img> the site ships has to carry these. `loading` keeps a photo
# below the fold off the critical path; `width`/`height` reserve its box so
# the text does not jump under a reader's thumb as it arrives. There are no
# raster images on the site today, so this is the rule waiting for the
# first one rather than a cleanup of existing ones.
IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)


def check_image_discipline() -> Finding:
    """Every <img>, in markup or in the scripts that build one."""
    bad: dict[str, str] = {}
    for page in SITE_PAGES:
        if not (REPO / page).exists():
            continue
        for tag in IMG_TAG.findall((REPO / page).read_text(encoding="utf-8")):
            missing = [a for a in ("loading=", "width=", "height=")
                       if a not in tag.lower()]
            if missing:
                bad[page] = "an <img> without " + ", ".join(missing)
    # The one place images actually arrive: a published review's portrait.
    reviews = REPO / "assets" / "reviews.js"
    if reviews.exists():
        text = reviews.read_text(encoding="utf-8")
        absent = [why for attr, why in (("loading", "lazy loading"),
                                        ("width", "a reserved width"),
                                        ("height", "a reserved height"))
                  if f".{attr}" not in text and f"'{attr}'" not in text]
        if absent:
            bad["assets/reviews.js"] = "review photos get no " + ", ".join(absent)
    return Finding(
        ok=not bad, blocking=False,
        what="Images are cheap to load",
        detail=("nothing loads a raster image yet, and the rule is in place"
                if not bad else
                "; ".join(f"{p}: {why}" for p, why in bad.items())),
        fix="give every <img> loading=lazy and an explicit width and height "
            "— without the dimensions the text jumps under the reader's "
            "thumb as each photo lands")


# What a link preview needs. Telegram and Instagram render these and
# nothing else; without them a marketing link is a bare grey rectangle, and
# the money behind the link is spent either way (P1-4).
OG_REQUIRED = ("og:title", "og:description", "og:image", "og:url", "og:locale")


def check_link_previews() -> Finding:
    """Every page, every language, plus an absolute image.

    The relative-image mistake gets its own test because it is the one that
    looks right in a browser and fails everywhere it matters: a preview is
    fetched by somebody else's server, which has no page to resolve it
    against.
    """
    problems: dict[str, str] = {}
    for page in SITE_PAGES:
        path = REPO / page
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        missing = [tag for tag in OG_REQUIRED
                   if f'property="{tag}"' not in text]
        if missing:
            problems[page] = "missing " + ", ".join(missing)
        elif 'name="twitter:card"' not in text:
            problems[page] = "no twitter:card"
        elif not re.search(r'property="og:image" content="https?://', text):
            problems[page] = "og:image is not an absolute URL"
    return Finding(
        ok=not problems, blocking=False,
        what="Link previews (Open Graph)",
        detail=("every page and language" if not problems else
                "; ".join(f"{p}: {why}" for p, why in problems.items())),
        fix="add the og: block — a shared link with none of it renders as a "
            "bare grey rectangle, and the ad spend behind it is the same")


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
        check_unshipped_claims(), check_review_honesty(),
        check_link_previews(), check_order_claim(), check_delivery_claim(),
        check_page_weight(), check_image_discipline(),
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
