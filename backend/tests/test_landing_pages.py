"""P2-1: the campaign landing pages, and the promises they make.

The main page is travel-locked, and the next campaign is New Year gifting.
A visitor who clicks a New Year ad and lands on "Your trip. Your photos."
has been told in the first second that they are in the wrong place, so each
campaign gets a page with a matched headline and the travel page stays as
specific as it is.

Ten pages generated from one template is a trade: one place to fix copy,
and the risk that the committed HTML quietly stops matching the script that
claims to produce it. The first test here is the whole reason the trade is
safe.
"""
import re

import pytest

from scripts import build_landings as bl

PAGES = bl.outputs()
SITE = "https://rspixel.uz"


def test_the_committed_pages_match_the_generator():
    """Edit the copy in the script and regenerate; do not edit the HTML.

    Without this, the generator becomes a lie the moment somebody fixes a
    typo in the output — and the next regeneration silently reverts them.
    """
    stale = [rel for rel, html in PAGES.items()
             if not (bl.REPO / rel).exists()
             or (bl.REPO / rel).read_text(encoding="utf-8") != html]
    assert not stale, ("stale, re-run `python scripts/build_landings.py`: "
                       + ", ".join(stale))


def test_both_occasions_exist_in_every_language():
    assert len(PAGES) == 10
    for slug in ("new-year", "family"):
        for d in ("", "ru/", "uz/", "uz-cyrl/", "kaa/"):
            assert f"{d}{slug}/index.html" in PAGES


@pytest.mark.parametrize("rel", PAGES)
def test_each_page_declares_its_own_url_and_canonical(rel):
    """Copying a block between pages and forgetting these is how every ad
    ends up pointing search engines at one page."""
    html = PAGES[rel]
    want = f"{SITE}/{rel[:-len('index.html')]}"
    assert f'<meta property="og:url" content="{want}">' in html
    assert f'<link rel="canonical" href="{want}">' in html


def test_every_page_has_a_distinct_url():
    urls = {re.search(r'property="og:url" content="([^"]+)"', h).group(1)
            for h in PAGES.values()}
    assert len(urls) == 10


@pytest.mark.parametrize("rel", PAGES)
def test_the_link_preview_is_complete(rel):
    """These are the pages a stranger sees FIRST — the ad points here, and
    the preview is what renders when the link is pasted into Telegram."""
    html = PAGES[rel]
    for tag in ("og:title", "og:description", "og:image", "og:url", "og:locale"):
        assert f'property="{tag}"' in html, tag
    assert 'name="twitter:card" content="summary_large_image"' in html
    assert re.search(r'property="og:image" content="https?://', html)


@pytest.mark.parametrize("rel", PAGES)
def test_the_language_links_stay_on_the_same_campaign(rel):
    """The bug this page exists to prevent, one level down: a visitor who
    switches language must land on the SAME campaign, not the home page.
    """
    slug = "new-year" if "new-year/" in rel else "family"
    html = PAGES[rel]
    # Two menus, header and footer, four other languages in each — so eight
    # is also the assertion that both menus are there and both are right.
    hrefs = re.findall(r'<a href="([^"]+)" lang="[^"]+" hreflang=', html)
    assert len(hrefs) == 8, hrefs
    for href in hrefs:
        assert href.endswith(f"{slug}/"), href
    # And the auto-redirect carries the campaign with it.
    assert f'data-page="{slug}/"' in html


@pytest.mark.parametrize("rel", PAGES)
def test_only_the_english_page_auto_redirects(rel):
    """Same rule as the main site: the root page sends a visitor to their
    language, the translated pages leave them where they clicked."""
    is_english = rel.split("/")[0] in ("new-year", "family")
    assert ('data-entry="root"' in PAGES[rel]) is is_english


@pytest.mark.parametrize("rel", PAGES)
def test_the_cta_reaches_the_editor(rel):
    html = PAGES[rel]
    depth = "../" if rel.split("/")[0] in ("new-year", "family") else "../../"
    assert f'href="{depth}editor/"' in html


@pytest.mark.parametrize("rel", PAGES)
def test_the_samples_are_labelled_samples(rel):
    """No book has been printed yet, so these are drawings. Three of them
    per page, each badged — an unbadged mock-up is a product photograph as
    far as a reader is concerned."""
    html = PAGES[rel]
    assert html.count('class="badge-sample"') == 3
    assert html.count('class="story-card"') == 3
    # Drawn, not photographed: no <img> anywhere on these pages.
    assert "<img" not in html


@pytest.mark.parametrize("rel", PAGES)
def test_no_page_advertises_something_unshipped(rel):
    """The same rule the main pages are held to (P0-3)."""
    assert not re.search(r"\bAI\b|\bнейросет|искусственн\w+ интеллект"
                         r"|sun.?iy intellekt|сунъий интеллект"
                         r"|jasalma intellekt|\bupscal", PAGES[rel], re.I)


class TestTheNewYearDeadline:
    """The one date on these pages that is a promise rather than a fact."""

    NY = [r for r in PAGES if "new-year/" in r]
    FAM = [r for r in PAGES if "family/" in r]

    @pytest.mark.parametrize("rel", NY)
    def test_the_new_year_page_states_a_cutoff(self, rel):
        """A New Year page with no cutoff is how somebody orders on 20
        December and is angry in January. It has to be on the page, in the
        language of the page."""
        lang = "en" if rel.startswith("new-year/") else rel.split("/")[0]
        assert bl.NEW_YEAR_ORDER_BY[lang] in PAGES[rel]

    @pytest.mark.parametrize("rel", NY)
    def test_it_also_says_what_happens_if_you_are_late(self, rel):
        """A deadline with no consequence stated reads as a suggestion."""
        html = PAGES[rel].lower()
        assert any(w in html for w in (
            "cannot promise", "не можем обещать", "vaʼda qila olmaymiz",
            "ваъда қила олмаймиз", "wáde ete almaymız"))

    @pytest.mark.parametrize("rel", FAM)
    def test_the_family_page_makes_no_seasonal_promise(self, rel):
        """It runs all year; a December date on it would go stale in January
        and nobody would notice."""
        for date in bl.NEW_YEAR_ORDER_BY.values():
            assert date not in PAGES[rel]

    def test_the_cutoff_is_one_edit_for_all_five_languages(self):
        assert set(bl.NEW_YEAR_ORDER_BY) == set(bl.LANGS)


class TestTheHeadlinesActuallyDiffer:
    """P2-1 in one assertion: if these pages read like the travel page,
    they have not solved anything and the ad spend still bounces."""

    def _h1(self, rel):
        return re.search(r"<h1>(.*?)</h1>", PAGES[rel], re.S).group(1)

    @pytest.mark.parametrize("rel", PAGES)
    def test_no_landing_page_leads_with_travel(self, rel):
        h1 = self._h1(rel).lower()
        assert not re.search(r"\btrip\b|travel|поездк|путешеств|sayohat"
                             r"|саёҳат|sayaxat", h1), h1

    def test_the_main_page_still_leads_with_travel(self):
        """The travel page is good BECAUSE it is specific. Broadening it was
        the option not taken, and this is what says so out loud."""
        home = (bl.REPO / "index.html").read_text(encoding="utf-8")
        assert "Your trip." in re.search(r"<h1>(.*?)</h1>", home, re.S).group(1)

    def test_each_occasion_has_its_own_headline(self):
        ny = {self._h1(r) for r in PAGES if "new-year/" in r}
        fam = {self._h1(r) for r in PAGES if "family/" in r}
        assert len(ny) == 5 and len(fam) == 5
        assert not (ny & fam)
