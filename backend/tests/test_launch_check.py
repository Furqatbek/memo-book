"""A81: the launch checklist is a program, not a paragraph.

Every placeholder in this product was tracked in prose. Prose is how
`ADMIN_TOKEN` came to be missing from the production env template, how the
admin lock test came to cover five routes out of eleven, and how
`Effect.ALERT_OPERATOR` sat declared and executed by nothing. Those were all
found by reading; the point of a script is not to need to.

These tests matter more than they look. A checklist that says "all clear" too
readily is worse than none — it is the same false confidence as a backup job
that runs nightly and stores nothing. So each check is exercised in both
directions: it must fire on the placeholder, and it must go quiet on a real
value.
"""
import pytest

from scripts import launch_check as lc

REAL = {
    "PRICES_CONFIRMED": "true",
    "SPINE_MM_16": "3.2", "SPINE_MM_32": "5.5",
    "SPINE_MM_48": "7.1", "SPINE_MM_96": "13.4",
    "ADMIN_TOKEN": "8f3c1d9a7b2e4f6081c5d3a9e7b1f4c2",
    "TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "-1001",
    "PAY_CARD_NUMBER": "8600 1234 5678 9012",
    "PAY_CARD_HOLDER": "FURQATBEK RAKHMATOV",
    "RESTIC_REPOSITORY": "s3:https://s3.example.net/bucket/rspixel",
}


class TestPrices:
    def test_fires_while_unconfirmed(self):
        assert not lc.check_prices({"PRICES_CONFIRMED": "false"}).ok

    def test_fires_when_the_key_is_absent_entirely(self):
        """Absent must read as "not confirmed". Treating a missing key as
        permission is how a checklist learns to lie."""
        assert not lc.check_prices({}).ok

    def test_quiet_once_confirmed(self):
        assert lc.check_prices(REAL).ok

    @pytest.mark.parametrize("value", ["TRUE", "yes", "1", "on"])
    def test_accepts_what_people_actually_type(self, value):
        assert lc.check_prices({"PRICES_CONFIRMED": value}).ok


class TestSpines:
    def test_fires_on_the_specs_invented_numbers(self):
        finding = lc.check_spines({k: v for k, v in lc.SPEC_SPINES.items()})
        assert not finding.ok
        assert "4 of 4" in finding.detail

    def test_fires_when_only_some_were_updated(self):
        """The half-done case is the dangerous one: two real tiers and two
        guesses looks finished from a distance."""
        partial = dict(lc.SPEC_SPINES)
        partial["SPINE_MM_16"] = "3.2"
        finding = lc.check_spines(partial)
        assert not finding.ok
        assert "3 of 4" in finding.detail

    def test_quiet_on_measured_values(self):
        assert lc.check_spines(REAL).ok

    def test_absent_keys_count_as_the_default_not_as_done(self):
        """The defaults ARE the spec's guesses, so an empty env is not a
        pass."""
        assert not lc.check_spines({}).ok


class TestAdminToken:
    @pytest.mark.parametrize("token", ["", "   ", "CHANGE_ME_ADMIN"])
    def test_fires_on_empty_or_placeholder(self, token):
        assert not lc.check_admin_token({"ADMIN_TOKEN": token}).ok

    def test_says_what_an_empty_token_actually_does(self):
        """"Not set" undersells it: the console does not exist, and says so
        with a 404 that looks like a wrong URL (A72)."""
        detail = lc.check_admin_token({"ADMIN_TOKEN": ""}).detail
        assert "404" in detail

    def test_quiet_on_a_real_token(self):
        assert lc.check_admin_token(REAL).ok


class TestTelegram:
    def test_fires_when_either_half_is_missing(self):
        assert not lc.check_telegram({"TELEGRAM_BOT_TOKEN": "123:abc"}).ok
        assert not lc.check_telegram({"TELEGRAM_CHAT_ID": "-1001"}).ok

    def test_quiet_when_both_are_set(self):
        assert lc.check_telegram(REAL).ok


class TestPayCard:
    def test_fires_on_the_placeholder_card(self):
        assert not lc.check_pay_card({
            "PAY_CARD_NUMBER": "8600 0000 0000 0000",
            "PAY_CARD_HOLDER": "FIRSTNAME LASTNAME"}).ok

    def test_fires_on_a_real_looking_number_with_a_placeholder_holder(self):
        """The half-filled case. Caught before, but only by accident — the
        number test was wrong and the holder covered for it."""
        assert not lc.check_pay_card({
            "PAY_CARD_NUMBER": "8600 1234 5678 9012",
            "PAY_CARD_HOLDER": "FIRSTNAME LASTNAME"}).ok

    def test_fires_on_zeros_behind_a_real_bin(self):
        """8600 is a real Uzcard prefix, so the number looks plausible at a
        glance and only the zeros give it away."""
        assert not lc.check_pay_card({
            "PAY_CARD_NUMBER": "8600 0000 0000 0000",
            "PAY_CARD_HOLDER": "FURQATBEK RAKHMATOV"}).ok

    def test_quiet_on_a_real_card(self):
        assert lc.check_pay_card(REAL).ok

    def test_does_not_cry_wolf_over_zeros_that_belong(self):
        """A real card can contain zeros — even a lot of them — as long as
        it is not ONLY zeros behind the BIN."""
        assert lc.check_pay_card({
            "PAY_CARD_NUMBER": "8600 1000 0000 0007",
            "PAY_CARD_HOLDER": "FURQATBEK RAKHMATOV"}).ok


class TestBackups:
    def test_fires_when_nothing_is_configured(self):
        assert not lc.check_backups({}).ok

    def test_fires_when_the_destination_is_this_machine(self):
        """The whole point is surviving the loss of the VPS."""
        finding = lc.check_backups({"RESTIC_REPOSITORY": "/srv/backups"})
        assert not finding.ok
        assert "this machine" in finding.detail

    def test_quiet_on_an_off_box_destination(self):
        assert lc.check_backups(REAL).ok

    def test_it_warns_rather_than_blocks(self):
        """No backups is serious and is not a reason to refuse to sell. The
        distinction keeps the STOP list honest."""
        assert not lc.check_backups({}).blocking


class TestTheSite:
    def test_it_reads_the_real_pages(self, tmp_path, monkeypatch):
        finding = lc.check_site_contacts()
        assert isinstance(finding.ok, bool)

    def test_it_fires_on_a_placeholder_page(self, tmp_path, monkeypatch):
        page = tmp_path / "index.html"
        page.write_text('<a href="tel:+998XXXXXXXXX">call</a>',
                        encoding="utf-8")
        monkeypatch.setattr(lc, "REPO", tmp_path)
        monkeypatch.setattr(lc, "SITE_PAGES", ["index.html"])
        assert not lc.check_site_contacts().ok

    def test_it_is_quiet_on_a_real_page(self, tmp_path, monkeypatch):
        page = tmp_path / "index.html"
        page.write_text('<a href="tel:+998901234567">call</a>',
                        encoding="utf-8")
        monkeypatch.setattr(lc, "REPO", tmp_path)
        monkeypatch.setattr(lc, "SITE_PAGES", ["index.html"])
        assert lc.check_site_contacts().ok

    def _pages(self, tmp_path, monkeypatch, bodies: dict):
        for name, body in bodies.items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        monkeypatch.setattr(lc, "REPO", tmp_path)
        monkeypatch.setattr(lc, "SITE_PAGES", list(bodies))

    def test_it_fires_when_the_pages_disagree(self, tmp_path, monkeypatch):
        """The failure that actually happens once the placeholders are gone:
        a number changed on one page and nowhere else. A stale real number
        looks entirely convincing, which is what makes it worse than a
        placeholder."""
        self._pages(tmp_path, monkeypatch, {
            "index.html": '<a href="tel:+998701647664">call</a>',
            "ru/index.html": '<a href="tel:+998900000000">call</a>',
        })
        finding = lc.check_site_contacts()
        assert not finding.ok
        assert "ru/index.html" in finding.detail

    def test_it_is_quiet_when_they_agree(self, tmp_path, monkeypatch):
        same = ('<a href="tel:+998701647664">call</a>'
                '<a href="mailto:a@b.uz">mail</a>'
                '<a href="https://t.me/Handle">tg</a>')
        self._pages(tmp_path, monkeypatch,
                    {"index.html": same, "ru/index.html": same})
        assert lc.check_site_contacts().ok

    def test_a_language_page_may_differ_in_everything_else(self, tmp_path,
                                                           monkeypatch):
        """Only the contact targets have to match. The pages are different
        languages with different copy and different relative links, and a
        check that demanded more would fire on every ordinary edit."""
        self._pages(tmp_path, monkeypatch, {
            "index.html": '<a href="editor/">Create</a>'
                          '<a href="tel:+998701647664">call</a>',
            "ru/index.html": '<a href="../editor/">Создать</a>'
                             '<a href="tel:+998701647664">звонок</a>',
        })
        assert lc.check_site_contacts().ok


class TestUnshippedClaims:
    """P0-3: the site sold AI enhancement, which does not exist. A customer
    who believed it would have uploaded blurry photos, received a blurry
    book, and asked for a reprint the margins cannot absorb."""

    def _page(self, tmp_path, monkeypatch, body: str):
        (tmp_path / "index.html").write_text(body, encoding="utf-8")
        monkeypatch.setattr(lc, "REPO", tmp_path)
        monkeypatch.setattr(lc, "SITE_PAGES", ["index.html"])

    @pytest.mark.parametrize("claim", [
        "<p>we use AI enhancement to improve blurry photos</p>",
        "<p>улучшаем фотографии с помощью нейросетей</p>",
        "<p>sunʼiy intellekt yordamida yaxshilaymiz</p>",
        "<p>сунъий интеллект ёрдамида яхшилаймиз</p>",
        "<p>jasalma intellekt járdeminde jaqsılaymız</p>",
        "<p>every photo is upscaled before printing</p>",
    ])
    def test_it_fires_in_every_language(self, tmp_path, monkeypatch, claim):
        """The claim was translated, so a check that only knew the English
        one would have found a fifth of it."""
        self._page(tmp_path, monkeypatch, claim)
        assert not lc.check_unshipped_claims().ok

    def test_it_is_quiet_on_the_honest_answer(self, tmp_path, monkeypatch):
        """The replacement describes the resolution warning the editor
        really shows."""
        self._page(tmp_path, monkeypatch,
                   "<p>The editor checks the resolution of every photo as "
                   "you place it. If an image is too small to print sharply "
                   "you will see a warning before you order.</p>")
        assert lc.check_unshipped_claims().ok

    def test_it_does_not_fire_on_a_denial(self, tmp_path, monkeypatch):
        """The trap this check fell into on its first draft. A pattern match
        cannot read a negation, so a word that appears in an honest denial —
        "we do NOT retouch photos" — must not be in the pattern at all. A
        checklist that goes red at a true sentence is one people learn to
        skip."""
        self._page(tmp_path, monkeypatch,
                   "<p>We do not sharpen or retouch photos: what you see in "
                   "the preview is what we print.</p>"
                   "<p>Мы не повышаем резкость и не ретушируем фотографии.</p>")
        assert lc.check_unshipped_claims().ok

    def test_the_real_site_is_clean(self):
        assert lc.check_unshipped_claims().ok

    def test_it_blocks_rather_than_warns(self, tmp_path, monkeypatch):
        """Selling something that does not exist is not a tidiness problem."""
        self._page(tmp_path, monkeypatch, "<p>AI enhancement</p>")
        assert lc.check_unshipped_claims().blocking


class TestReviewHonesty:
    """P1-3: the reviews section is a statement of integrity while it is
    empty. The cheapest way to fill it is a stock avatar beside an invented
    quote, which is what a competitor does — so the cheapest way must fail
    loudly."""

    def _files(self, tmp_path, monkeypatch, bodies: dict):
        for name, body in bodies.items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        monkeypatch.setattr(lc, "REPO", tmp_path)
        monkeypatch.setattr(lc, "SITE_PAGES", [n for n in bodies
                                               if n.endswith(".html")])
        monkeypatch.setattr(lc, "REVIEW_SOURCES", [n for n in bodies
                                                   if n.endswith(".js")])

    @pytest.mark.parametrize("url", [
        "https://i.pravatar.cc/100",
        "https://ui-avatars.com/api/?name=A",
        "https://api.dicebear.com/7.x/avataaars/svg",
        "https://randomuser.me/api/portraits/women/1.jpg",
        "https://www.gravatar.com/avatar/abc",
        "https://via.placeholder.com/80",
        "https://source.unsplash.com/random/80x80",
    ])
    def test_it_fires_on_a_face_nobody_owns(self, tmp_path, monkeypatch, url):
        self._files(tmp_path, monkeypatch,
                    {"index.html": f'<img src="{url}">'})
        assert not lc.check_review_honesty().ok

    def test_it_fires_on_a_photo_hosted_elsewhere(self, tmp_path, monkeypatch):
        """A remote photograph is somebody else's picture: it can change or
        vanish after it has been vouched for."""
        self._files(tmp_path, monkeypatch, {
            "assets/reviews.js": "{ name:'A', photo: 'https://example.org/a.jpg' }"})
        assert not lc.check_review_honesty().ok

    def test_it_is_quiet_on_a_photo_we_hold(self, tmp_path, monkeypatch):
        self._files(tmp_path, monkeypatch, {
            "assets/reviews.js": "{ name:'A', photo: 'reviews/aziza.jpg' }"})
        assert lc.check_review_honesty().ok

    def test_an_empty_section_is_honest(self, tmp_path, monkeypatch):
        """No reviews is not a failure. It is the current, true state."""
        self._files(tmp_path, monkeypatch, {"assets/reviews.js": "var REVIEWS = [];"})
        assert lc.check_review_honesty().ok

    def test_the_real_site_is_clean(self):
        assert lc.check_review_honesty().ok

    def test_it_blocks_rather_than_warns(self, tmp_path, monkeypatch):
        self._files(tmp_path, monkeypatch,
                    {"index.html": '<img src="https://i.pravatar.cc/100">'})
        assert lc.check_review_honesty().blocking


class TestLinkPreviews:
    """P1-4: what renders in a Telegram card is the advertisement."""

    def _page(self, tmp_path, monkeypatch, body: str):
        (tmp_path / "index.html").write_text(body, encoding="utf-8")
        monkeypatch.setattr(lc, "REPO", tmp_path)
        monkeypatch.setattr(lc, "SITE_PAGES", ["index.html"])

    GOOD = ('<meta property="og:title" content="t">'
            '<meta property="og:description" content="d">'
            '<meta property="og:image" content="https://rspixel.uz/assets/og.png">'
            '<meta property="og:url" content="https://rspixel.uz/">'
            '<meta property="og:locale" content="en_GB">'
            '<meta name="twitter:card" content="summary_large_image">')

    def test_it_is_quiet_on_a_complete_head(self, tmp_path, monkeypatch):
        self._page(tmp_path, monkeypatch, self.GOOD)
        assert lc.check_link_previews().ok

    @pytest.mark.parametrize("drop", list(lc.OG_REQUIRED))
    def test_it_names_whichever_tag_is_missing(self, tmp_path, monkeypatch, drop):
        body = "".join(line for line in self.GOOD.split("><")
                       if f'property="{drop}"' not in line)
        self._page(tmp_path, monkeypatch, body)
        finding = lc.check_link_previews()
        assert not finding.ok
        assert drop in finding.detail

    def test_it_fires_on_a_relative_image(self, tmp_path, monkeypatch):
        """The mistake that looks right in a browser and fails everywhere it
        matters: a preview is fetched by somebody else's server, which has
        no page to resolve a relative path against."""
        self._page(tmp_path, monkeypatch,
                   self.GOOD.replace("https://rspixel.uz/assets/og.png",
                                     "assets/og.png"))
        finding = lc.check_link_previews()
        assert not finding.ok
        assert "absolute" in finding.detail

    def test_it_fires_without_a_twitter_card(self, tmp_path, monkeypatch):
        self._page(tmp_path, monkeypatch,
                   self.GOOD.replace('<meta name="twitter:card" '
                                     'content="summary_large_image">', ""))
        assert not lc.check_link_previews().ok

    def test_the_real_pages_are_complete(self):
        assert lc.check_link_previews().ok

    def test_it_warns_rather_than_blocks(self, tmp_path, monkeypatch):
        """A grey preview card is lost reach, not a broken product — it must
        not sit on the STOP list beside selling something that does not
        exist."""
        self._page(tmp_path, monkeypatch, "<p>nothing</p>")
        assert not lc.check_link_previews().blocking


class TestTheReportItself:
    def test_it_exits_non_zero_while_anything_blocks(self, capsys):
        assert lc.main() == 1

    def test_every_failure_carries_a_fix(self, capsys):
        """A checklist that names a problem without naming the next action
        is a source of guilt, not a tool."""
        env = {}
        for finding in (lc.check_prices(env), lc.check_spines(env),
                        lc.check_admin_token(env), lc.check_telegram(env),
                        lc.check_pay_card(env), lc.check_backups(env),
                        lc.check_site_contacts(), lc.check_test_book()):
            if not finding.ok:
                assert finding.fix.strip(), f"{finding.what} has no fix"

    def test_the_test_book_cannot_be_ticked_by_accident(self):
        """The one item no program can verify. It stays outstanding until a
        human explicitly says a book was printed and inspected."""
        assert not lc.check_test_book().ok or (
            lc.REPO / "docs" / ".test-book-printed").exists()


class TestProductionMode:
    def test_fires_when_env_is_unset(self):
        """The default is "dev", which is right for a laptop and wrong for a
        public host: it puts /docs and the full schema back (A82)."""
        finding = lc.check_env_is_production({})
        assert not finding.ok
        assert "/docs" in finding.detail

    @pytest.mark.parametrize("value", ["dev", "staging", "DEV", ""])
    def test_fires_on_anything_that_is_not_prod(self, value):
        assert not lc.check_env_is_production({"ENV": value}).ok

    def test_quiet_on_prod(self):
        assert lc.check_env_is_production({"ENV": "prod"}).ok

    def test_it_mentions_the_admin_routes(self):
        """The reason this matters is not tidiness — the schema is what
        makes A72's hidden admin API findable."""
        assert "admin" in lc.check_env_is_production({}).detail
