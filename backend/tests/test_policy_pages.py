"""P2-4: the privacy policy and the terms.

A privacy policy is the one page on a site where a sentence that is not
true is worse than a sentence that is missing — it is read precisely when
somebody has stopped trusting you, and it is the document a payment
acquirer checks. So these tests are less about the pages existing than
about the facts in them still matching the code that implements them.

The load-bearing one is `test_the_stated_retention_matches_the_code`:
change `DRAFT_RETENTION` and the policy becomes a lie, silently, in five
languages at once.
"""
import re

import pytest

from app.services.books import DRAFT_RETENTION
from scripts import build_policies as bp

PAGES = bp.outputs()
SITE = "https://rspixel.uz"
CYRILLIC = re.compile(r"[Ѐ-ӿ]")


def text_of(rel: str) -> str:
    """Visible text, with tags and the head stripped out."""
    body = PAGES[rel].partition("<body")[2]
    return re.sub(r"<[^>]+>", " ", body)


def doc_text_of(rel: str) -> str:
    """Just the document itself, without the chrome. The language menu
    carries "Русский" and "Ўзбекча" on every page by design, so a script
    scan over the whole page would flag every Latin page there is."""
    main = PAGES[rel].partition("<main")[2].partition("</main>")[0]
    return re.sub(r"<[^>]+>", " ", main)


def test_the_committed_pages_match_the_generator():
    stale = [rel for rel, html in PAGES.items()
             if not (bp.REPO / rel).exists()
             or (bp.REPO / rel).read_text(encoding="utf-8") != html]
    assert not stale, ("stale, re-run `python scripts/build_policies.py`: "
                       + ", ".join(stale))


def test_both_documents_exist_in_every_language():
    assert len(PAGES) == 10
    for slug in ("privacy", "terms"):
        for d in ("", "ru/", "uz/", "uz-cyrl/", "kaa/"):
            assert f"{d}{slug}/index.html" in PAGES


@pytest.mark.parametrize("rel", PAGES)
def test_each_page_declares_its_own_url(rel):
    want = f"{SITE}/{rel[:-len('index.html')]}"
    assert f'<meta property="og:url" content="{want}">' in PAGES[rel]
    assert f'<link rel="canonical" href="{want}">' in PAGES[rel]


class TestTheFactsMatchTheCode:
    """Every number in the policy was read out of the implementation."""

    PRIVACY = [r for r in PAGES if "privacy/" in r]

    def test_the_stated_retention_matches_the_code(self):
        """If DRAFT_RETENTION ever changes, this is what stops the policy
        quietly becoming false in five languages."""
        assert DRAFT_RETENTION.days == 30
        for rel in self.PRIVACY:
            assert str(DRAFT_RETENTION.days) in text_of(rel), rel

    def test_expiry_really_deletes_the_files_it_promises_to_delete(self):
        """The policy says the photographs go with the book. That is only
        true because lifecycle collects the storage keys before expiring."""
        from app.services import lifecycle
        src = lifecycle.__loader__.get_source("app.services.lifecycle")
        assert "_storage_keys_for_book" in src
        assert "storage.delete_keys" in src

    def test_orders_are_never_auto_expired_so_the_policy_does_not_claim_they_are(self):
        """A book that reached locked/ordered is never expired, so the
        document says order files are kept until asked rather than naming a
        period nothing implements."""
        from app.services import lifecycle
        src = lifecycle.__loader__.get_source("app.services.lifecycle")
        assert "BookStatus.DRAFT.value" in src


class TestTheRequiredStatements:
    """The five things the brief said the policy must state."""

    PRIVACY = [r for r in PAGES if "privacy/" in r]

    @pytest.mark.parametrize("rel", PRIVACY)
    def test_it_says_how_to_make_contact(self, rel):
        assert "+998 70 164-76-64" in text_of(rel)
        assert "merelyriki@gmail.com" in text_of(rel)

    @pytest.mark.parametrize("rel", PRIVACY)
    def test_it_says_the_location_is_stripped(self, rel):
        """The engineering half of P2-4, stated to the customer. It is a
        true claim — tests/test_exif_privacy.py proves it against a
        GPS-tagged fixture — and it is worth saying out loud."""
        body = text_of(rel).lower()
        assert any(w in body for w in ("coordinates", "координат", "koordinata",
                                       "координата", "koordinatalar"))

    @pytest.mark.parametrize("rel", PRIVACY)
    def test_it_has_every_section(self, rel):
        assert PAGES[rel].count("<h2>") == 7, rel

    @pytest.mark.parametrize("rel", PAGES)
    def test_the_documents_link_to_each_other(self, rel):
        other = "terms" if "privacy/" in rel else "privacy"
        assert f"{other}/" in PAGES[rel], rel


class TestTranslationHygiene:
    """Five languages, two of them sharing an alphabet with a third that
    does not. A Cyrillic letter pasted into a Latin word renders as a word
    nobody can search for and nothing flags."""

    LATIN = [r for r in PAGES
             if r.split("/")[0] in ("privacy", "terms")
             or r.startswith(("uz/", "kaa/"))]

    @pytest.mark.parametrize("rel", LATIN)
    def test_no_cyrillic_in_a_latin_script_page(self, rel):
        hits = CYRILLIC.findall(doc_text_of(rel))
        assert not hits, f"{rel} mixes Cyrillic {set(hits)} into Latin text"

    @pytest.mark.parametrize("rel", [r for r in PAGES
                                     if r.startswith(("ru/", "uz-cyrl/"))])
    def test_a_cyrillic_page_is_actually_cyrillic(self, rel):
        assert len(CYRILLIC.findall(doc_text_of(rel))) > 200, rel
