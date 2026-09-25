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
import re

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


class TestOrderClaim:
    """P1-5: the card that sells auto-layout has to say what it does.

    Auto-layout does not merely fill pages — anything fills pages. It sorts
    by EXIF `taken_at` (R2) and rebuilds the trip in the order it happened.
    These tests are about the five-way copy, not the rule; the rule is
    covered by tests/domain/test_ordering.py and
    tests/api/test_placement.py::test_chronological_order_full_bleed.
    """

    # The card as it read before P1-5: names the feature, claims nothing.
    OLD = {
        "index.html": "<h3>Auto-placement</h3>\n<p>One click fills your pages.</p>",
        "ru/index.html": "<h3>Автозаполнение</h3>\n<p>Фото расставлены по страницам.</p>",
        "uz/index.html": "<h3>Avtomatik joylashtirish</h3>\n<p>Suratlar sahifalarga joylashadi.</p>",
        "uz-cyrl/index.html": "<h3>Автоматик жойлаштириш</h3>\n<p>Суратлар саҳифаларга жойлашади.</p>",
        "kaa/index.html": "<h3>Avtomatikalıq jaylastırıw</h3>\n<p>Súwretler betlerge jaylasadı.</p>",
    }

    def _tree(self, tmp_path, monkeypatch, overrides: dict[str, str]):
        """A copy of the real five pages, with some cards swapped out."""
        for page in lc.ORDER_CLAIM:
            dest = tmp_path / page
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(overrides.get(page, (lc.REPO / page).read_text(
                encoding="utf-8")), encoding="utf-8")
        monkeypatch.setattr(lc, "REPO", tmp_path)

    def test_the_real_pages_all_make_the_claim(self):
        assert lc.check_order_claim().ok

    @pytest.mark.parametrize("page", list(OLD))
    def test_one_language_reverting_is_enough_to_fire(self, tmp_path,
                                                      monkeypatch, page):
        """Four correct pages must not hide the fifth. This is the failure
        this check exists for: the copy is edited in the language the editor
        reads and drifts silently in the four nobody opened."""
        self._tree(tmp_path, monkeypatch, {page: self.OLD[page]})
        finding = lc.check_order_claim()
        assert not finding.ok
        assert page in finding.detail
        assert "chronological" in finding.detail

    def test_it_reports_a_missing_card_separately(self, tmp_path, monkeypatch):
        self._tree(tmp_path, monkeypatch, {"ru/index.html": "<p>no card</p>"})
        finding = lc.check_order_claim()
        assert not finding.ok
        assert "no auto-layout card" in finding.detail

    def test_renaming_the_card_is_reported_as_the_claim_going_missing(
            self, tmp_path, monkeypatch):
        """The English pattern matches the card under its old name too, so
        a rename reports the real reason rather than 'no card found'."""
        self._tree(tmp_path, monkeypatch, {"index.html": self.OLD["index.html"]})
        assert "chronological" in lc.check_order_claim().detail

    def test_the_claim_may_live_in_the_heading_alone(self, tmp_path, monkeypatch):
        """Heading or body — the claim has to be made, not made twice."""
        self._tree(tmp_path, monkeypatch, {
            "uz/index.html": "<h3>Tartib bilan avtomatik joylashtirish</h3>"
                             "\n<p>Bir bosishda joylashadi.</p>"})
        assert lc.check_order_claim().ok

    def test_it_warns_rather_than_blocks(self, tmp_path, monkeypatch):
        """Under-selling a real feature costs sales, not customers."""
        self._tree(tmp_path, monkeypatch, dict(self.OLD))
        finding = lc.check_order_claim()
        assert not finding.ok and not finding.blocking


# Split by slug, not slash count: "new-year/index.html" is as shallow as
# "ru/index.html". Module level because a class body cannot see its own
# names from inside a comprehension.
LANDING_PAGES = [p for p in lc.SITE_PAGES
                 if any(f"{s}/" in p for s in lc.LANDING_SLUGS)]
MAIN_PAGES = [p for p in lc.SITE_PAGES if p not in LANDING_PAGES]


class TestDeliveryClaim:
    """P1-6: a buyer outside Tashkent asks "do you even reach me?" first.

    Every page must say it in the footer. A page that HAS an FAQ must say it
    there too, where somebody looking for it goes to look — but a campaign
    landing page sends its FAQ traffic to the main page, so it is held to
    the footer alone rather than failing for a section it deliberately does
    not have.
    """

    FOOTER_LINE = re.compile(
        r"\n\s*<p>[^<]*(?:deliver anywhere in Uzbekistan"
        r"|любую точку Узбекистана|istalgan nuqtasiga yetkazib"
        r"|исталган нуқтасига етказиб|qálegen jerine jetkerip)[^<]*</p>", re.I)
    IN_FAQ = re.compile(r"deliver anywhere|любую точку|istalgan nuqtasiga"
                        r"|исталган нуқтасига|qálegen jerine", re.I)

    def _tree(self, tmp_path, monkeypatch, edits):
        for page in lc.SITE_PAGES:
            dest = tmp_path / page
            dest.parent.mkdir(parents=True, exist_ok=True)
            text = (lc.REPO / page).read_text(encoding="utf-8")
            if page in edits:
                text = edits[page](text)
            dest.write_text(text, encoding="utf-8")
        monkeypatch.setattr(lc, "REPO", tmp_path)

    @classmethod
    def _drop_faq(cls, text):
        head, sep, foot = text.partition("<footer")
        for block in re.findall(r"      <details>.*?</details>\n", head, re.S):
            if cls.IN_FAQ.search(block):
                head = head.replace(block, "", 1)
                break
        return head + sep + foot

    @classmethod
    def _drop_footer(cls, text):
        head, sep, foot = text.partition("<footer")
        return head + sep + cls.FOOTER_LINE.sub("", foot, count=1)

    LANDING = LANDING_PAGES
    MAIN = MAIN_PAGES

    def test_the_real_pages_all_state_it(self):
        assert lc.check_delivery_claim().ok

    def test_every_page_is_covered_not_just_the_main_five(self):
        assert len(self.MAIN) == 5
        assert len(self.LANDING) == 10

    @pytest.mark.parametrize("page", MAIN)
    def test_a_missing_faq_entry_fires(self, tmp_path, monkeypatch, page):
        self._tree(tmp_path, monkeypatch, {page: self._drop_faq})
        finding = lc.check_delivery_claim()
        assert not finding.ok
        assert page in finding.detail and "not in the FAQ" in finding.detail

    @pytest.mark.parametrize("page", MAIN + LANDING)
    def test_a_missing_footer_line_fires(self, tmp_path, monkeypatch, page):
        """The footer is the half likeliest to be forgotten — the same line
        in fifteen files, and nobody reads it on purpose."""
        self._tree(tmp_path, monkeypatch, {page: self._drop_footer})
        finding = lc.check_delivery_claim()
        assert not finding.ok
        assert page in finding.detail and "not in the footer" in finding.detail

    def test_a_landing_page_is_not_asked_for_an_FAQ_it_does_not_have(self):
        """It would otherwise be impossible to satisfy without bolting an
        FAQ onto a page whose whole point is to be short."""
        for page in self.LANDING:
            assert 'class="faq-list"' not in (lc.REPO / page).read_text(
                encoding="utf-8"), page
        assert lc.check_delivery_claim().ok

    def test_it_names_both_when_a_main_page_says_it_nowhere(self, tmp_path,
                                                            monkeypatch):
        self._tree(tmp_path, monkeypatch, {
            "kaa/index.html": lambda t: self._drop_footer(self._drop_faq(t))})
        detail = lc.check_delivery_claim().detail
        assert "not in the FAQ and not in the footer" in detail

    def test_the_karakalpak_pages_are_covered(self, tmp_path, monkeypatch):
        """The brief singled it out: its readers are furthest from the print
        shop and likeliest to assume the answer is no."""
        kaa = [p for p in lc.SITE_PAGES if p.startswith("kaa/")]
        assert len(kaa) == 3
        self._tree(tmp_path, monkeypatch, {"kaa/new-year/index.html": self._drop_footer})
        assert not lc.check_delivery_claim().ok

    def test_it_warns_rather_than_blocks(self, tmp_path, monkeypatch):
        self._tree(tmp_path, monkeypatch,
                   {p: self._drop_footer for p in lc.SITE_PAGES})
        finding = lc.check_delivery_claim()
        assert not finding.ok and not finding.blocking


class TestPageWeight:
    """P2-3: the audience is on mobile data.

    Nothing is slow today — the site carries no raster images at all and
    comes to about 19 KB gzipped — which is the point of writing the budget
    now. It is here so the first real photograph cannot quietly turn a 19 KB
    page into a 2 MB one. A budget written after the regression is a
    post-mortem.
    """

    def _site(self, tmp_path, monkeypatch, extra=b"", ref=""):
        page = tmp_path / "index.html"
        page.write_text(f'<link href="assets/style.css" rel="stylesheet">{ref}',
                        encoding="utf-8")
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "style.css").write_bytes(b"body{}" + extra)
        monkeypatch.setattr(lc, "REPO", tmp_path)
        monkeypatch.setattr(lc, "SITE_PAGES", ["index.html"])

    def test_the_real_site_is_inside_the_budget(self):
        finding = lc.check_page_weight()
        assert finding.ok, finding.detail

    def test_the_real_site_is_nowhere_near_the_budget(self):
        """If this ever gets close, the number in the detail line is the
        early warning — it names the heaviest page and its size."""
        assert "of 120 KB" in lc.check_page_weight().detail

    def test_a_fat_asset_fires(self, tmp_path, monkeypatch):
        self._site(tmp_path, monkeypatch, extra=b"x" * (130 * 1024))
        finding = lc.check_page_weight()
        assert not finding.ok
        assert "index.html" in finding.detail

    def test_one_oversized_photo_fires_even_inside_the_page_budget(
            self, tmp_path, monkeypatch):
        """A single heavy image is worth naming on its own: the page total
        can still look fine while one photo does all the damage."""
        self._site(tmp_path, monkeypatch, ref='<img src="assets/hero.jpg">')
        (tmp_path / "assets" / "hero.jpg").write_bytes(b"x" * (210 * 1024))
        finding = lc.check_page_weight()
        assert not finding.ok
        assert "hero.jpg" in finding.detail

    def test_it_ignores_links_to_other_pages(self, tmp_path, monkeypatch):
        """`href="../ru/new-year/"` is a page, not an asset — counting those
        would make the budget meaningless."""
        self._site(tmp_path, monkeypatch, ref='<a href="../ru/new-year/">ru</a>')
        assert lc.check_page_weight().ok

    def test_it_warns_rather_than_blocks(self, tmp_path, monkeypatch):
        self._site(tmp_path, monkeypatch, extra=b"x" * (130 * 1024))
        assert not lc.check_page_weight().blocking


class TestImageDiscipline:
    """The rule waiting for the first photograph, not a cleanup of existing
    ones: there are no raster images on the site yet."""

    def test_the_real_site_passes(self):
        finding = lc.check_image_discipline()
        assert finding.ok, finding.detail

    @pytest.mark.parametrize("tag,missing", [
        ('<img src="a.jpg">', "loading="),
        ('<img src="a.jpg" loading="lazy">', "width="),
        ('<img src="a.jpg" loading="lazy" width="44">', "height="),
    ])
    def test_an_img_missing_an_attribute_fires(self, tmp_path, monkeypatch,
                                               tag, missing):
        (tmp_path / "index.html").write_text(tag, encoding="utf-8")
        monkeypatch.setattr(lc, "REPO", tmp_path)
        monkeypatch.setattr(lc, "SITE_PAGES", ["index.html"])
        finding = lc.check_image_discipline()
        assert not finding.ok
        assert missing in finding.detail

    def test_a_complete_img_passes(self, tmp_path, monkeypatch):
        (tmp_path / "index.html").write_text(
            '<img src="a.jpg" loading="lazy" width="44" height="44">',
            encoding="utf-8")
        monkeypatch.setattr(lc, "REPO", tmp_path)
        monkeypatch.setattr(lc, "SITE_PAGES", ["index.html"])
        assert lc.check_image_discipline().ok

    def test_review_photos_reserve_their_box(self):
        """The one place an <img> actually arrives. Without width and height
        the quote jumps under the reader's thumb as each portrait lands, and
        it only shows up once real reviews are published — long after the
        code was written."""
        js = (lc.REPO / "assets" / "reviews.js").read_text(encoding="utf-8")
        for attr in ("loading", "decoding", "width", "height"):
            assert f".{attr}" in js, attr

    def test_it_notices_if_review_photos_lose_their_dimensions(
            self, tmp_path, monkeypatch):
        (tmp_path / "index.html").write_text("<p>no images</p>", encoding="utf-8")
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "reviews.js").write_text(
            "img.loading = 'lazy';", encoding="utf-8")
        monkeypatch.setattr(lc, "REPO", tmp_path)
        monkeypatch.setattr(lc, "SITE_PAGES", ["index.html"])
        finding = lc.check_image_discipline()
        assert not finding.ok
        assert "reviews.js" in finding.detail


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
