"""A83: the site ships the same set of files by both routes, and says the
same thing in its sitemap as in its markup.

Three places enumerate the marketing site by hand: the Dockerfile's COPY
list, the Pages workflow's `cp -r` line, and that workflow's `paths:`
trigger. A file added to the repository and to only one of them is served in
one place and silently missing in the other — and "silently missing" for a
`robots.txt` or a `sitemap.xml` means a search engine never sees it, which
nothing in the product would ever complain about.

Same shape as the admin route list and the rate-limit inventory: derive it,
do not promise it.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO / "deploy" / "Dockerfile"
PAGES = REPO / ".github" / "workflows" / "deploy-pages.yml"

SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9",
              "x": "http://www.w3.org/1999/xhtml"}


def docker_site_files() -> set[str]:
    """What the production image puts under SITE_DIR."""
    found = re.findall(r"^COPY\s+(\S+)\s+/app/site/",
                       DOCKERFILE.read_text(encoding="utf-8"), re.M)
    assert found, "no site COPY lines in the Dockerfile — did it move?"
    return set(found)


def pages_site_files() -> set[str]:
    """What the GitHub Pages workflow publishes."""
    line = re.search(r"^\s*cp -r (.+) \"\$SITE\"/\s*$",
                     PAGES.read_text(encoding="utf-8"), re.M)
    assert line, "no `cp -r ... $SITE` line in the Pages workflow"
    # `editor` ships to Pages but is mounted separately in the image.
    return set(line.group(1).split()) - {"editor"}


class TestBothRoutesShipTheSameSite:
    def test_the_image_and_pages_agree(self):
        in_image, in_pages = docker_site_files(), pages_site_files()
        assert in_image == in_pages, (
            "the two deploy routes disagree about what the site is — "
            f"image only: {sorted(in_image - in_pages)}, "
            f"pages only: {sorted(in_pages - in_image)}")

    def test_everything_they_ship_actually_exists(self):
        for name in docker_site_files() | pages_site_files():
            assert (REPO / name).exists(), f"{name} is copied but not in the repo"

    @pytest.mark.parametrize("name", ["robots.txt", "sitemap.xml"])
    def test_the_crawler_files_are_shipped(self, name):
        """Named individually: these are the two whose absence nothing in the
        product would ever surface."""
        assert name in docker_site_files()
        assert name in pages_site_files()

    def test_the_workflow_reruns_when_they_change(self):
        """Shipping them is not enough if editing one does not trigger a
        deploy — the file would sit correct in the repo and stale on the
        site."""
        triggers = PAGES.read_text(encoding="utf-8")
        for name in ("robots.txt", "sitemap.xml"):
            assert f'- "{name}"' in triggers, f"{name} does not trigger a deploy"


class TestRobots:
    def test_it_points_at_the_sitemap_we_actually_publish(self):
        robots = (REPO / "robots.txt").read_text(encoding="utf-8")
        assert "Sitemap: https://rspixel.uz/sitemap.xml" in robots

    def test_it_does_not_hide_the_site_itself(self):
        """A stray `Disallow: /` is the classic way to deindex a business
        overnight."""
        robots = (REPO / "robots.txt").read_text(encoding="utf-8")
        assert not re.search(r"^Disallow:\s*/\s*$", robots, re.M)

    @pytest.mark.parametrize("path", ["/editor/", "/admin/"])
    def test_the_applications_are_kept_out_of_the_index(self, path):
        assert f"Disallow: {path}" in (REPO / "robots.txt").read_text(
            encoding="utf-8")


def sitemap_root():
    import xml.etree.ElementTree as ET
    return ET.parse(REPO / "sitemap.xml").getroot()


def page_for(loc: str) -> Path:
    """https://rspixel.uz/ru/ -> <repo>/ru/index.html"""
    rel = loc.removeprefix("https://rspixel.uz/").strip("/")
    return REPO / (f"{rel}/index.html" if rel else "index.html")


class TestSitemap:
    def test_it_lists_every_language_page_and_no_others(self):
        listed = {u.find("s:loc", SITEMAP_NS).text
                  for u in sitemap_root().findall("s:url", SITEMAP_NS)}
        real = {"https://rspixel.uz/"} | {
            f"https://rspixel.uz/{d}/" for d in ("ru", "uz", "uz-cyrl", "kaa")
            if (REPO / d / "index.html").exists()}
        assert listed == real

    def test_every_url_resolves_to_a_page_in_the_repo(self):
        for url in sitemap_root().findall("s:url", SITEMAP_NS):
            loc = url.find("s:loc", SITEMAP_NS).text
            assert page_for(loc).exists(), f"{loc} has no page behind it"

    def test_each_url_carries_the_whole_cluster(self):
        """The protocol requires it: a cluster is only valid if every member
        points at every member, itself included."""
        urls = sitemap_root().findall("s:url", SITEMAP_NS)
        expected = {"en", "ru", "uz", "uz-Cyrl", "kaa", "x-default"}
        for url in urls:
            got = {a.get("hreflang") for a in url.findall("x:link", SITEMAP_NS)}
            assert got == expected, (
                f"{url.find('s:loc', SITEMAP_NS).text} declares {sorted(got)}")

    def test_it_agrees_with_the_markup(self):
        """A sitemap that disagreed with the pages' own hreflang tags would
        be worse than neither — case included, since "uz-Cyrl" is not
        "uz-cyrl"."""
        markup = dict(re.findall(
            r'hreflang="([^"]+)" href="([^"]+)"',
            (REPO / "index.html").read_text(encoding="utf-8")))
        first = sitemap_root().find("s:url", SITEMAP_NS)
        sitemap = {a.get("hreflang"): a.get("href")
                   for a in first.findall("x:link", SITEMAP_NS)}
        assert sitemap == markup

    def test_no_lastmod_it_cannot_keep_honest(self):
        """Hand-written, so any date here goes stale the next time the site
        changes — and a lastmod that cannot be trusted is worse than none."""
        assert not sitemap_root().findall(".//s:lastmod", SITEMAP_NS)
