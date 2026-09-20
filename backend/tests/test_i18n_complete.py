"""Every customer-facing string exists in every language we offer.

The editor ships five locales. A key added to one and forgotten in the
others does not crash anything — `t()` falls back, and the customer is shown
a raw key like `receipt.title` in the middle of an otherwise finished page.
That is the quiet kind of failure this repo keeps finding: nothing errors,
nothing logs, and it only looks wrong to someone reading that language.

There was no check for this until a feature needed nine new strings in five
languages at once (A100), which is exactly the change that gets it wrong.

The file is JavaScript, so it is read as text rather than imported. The keys
are quoted literals at a known indent, which is enough — and if that ever
stops being true the parse finds no keys and the first assertion fails
loudly rather than passing on an empty set.
"""
import re
from pathlib import Path

import pytest

I18N = Path(__file__).resolve().parents[2] / "editor" / "js" / "i18n.js"

# A locale block opens with `en: {` or `'uz-cyrl': {` at two-space indent.
LOCALE = re.compile(r"^ {2}'?([a-z-]+)'?: \{$", re.M)
# A string entry inside one: `'some.key': '...'` at four-space indent.
ENTRY = re.compile(r"^ {4}'([^']+)':", re.M)


def locales() -> dict[str, set[str]]:
    text = I18N.read_text(encoding="utf-8")
    starts = [(m.group(1), m.start()) for m in LOCALE.finditer(text)]
    assert starts, "no locale blocks found — has i18n.js changed shape?"
    out: dict[str, set[str]] = {}
    for i, (name, start) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(text)
        out[name] = set(ENTRY.findall(text[start:end]))
    return out


ALL = locales()
REFERENCE = "en"


def test_the_languages_we_promise_are_all_there():
    """Five, per the product's own promise. Losing one silently would mean
    a whole audience reading somebody else's language."""
    assert set(ALL) == {"en", "ru", "uz", "uz-cyrl", "kaa"}


def test_english_has_a_sensible_number_of_strings():
    """Guards the parse itself: a regex that matched nothing would make
    every comparison below trivially true."""
    assert len(ALL[REFERENCE]) > 100


@pytest.mark.parametrize("locale", [name for name in ALL if name != REFERENCE])
def test_no_language_is_missing_a_string(locale):
    missing = sorted(ALL[REFERENCE] - ALL[locale])
    assert not missing, (
        f"{locale} is missing {len(missing)} string(s) that English has — "
        f"a customer reading {locale} sees the raw key: {missing[:8]}")


@pytest.mark.parametrize("locale", [name for name in ALL if name != REFERENCE])
def test_no_language_has_a_string_english_does_not(locale):
    """A key only one language has is either a typo in that language or a
    string deleted from English and left behind everywhere else."""
    extra = sorted(ALL[locale] - ALL[REFERENCE])
    assert not extra, f"{locale} has keys English does not: {extra[:8]}"


def test_no_locale_repeats_a_key():
    """A duplicate key is legal JavaScript and silently wins or loses
    depending on which one is written last."""
    text = I18N.read_text(encoding="utf-8")
    starts = [(m.group(1), m.start()) for m in LOCALE.finditer(text)]
    for i, (name, start) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(text)
        found = ENTRY.findall(text[start:end])
        dupes = sorted({k for k in found if found.count(k) > 1})
        assert not dupes, f"{name} defines these twice: {dupes}"
