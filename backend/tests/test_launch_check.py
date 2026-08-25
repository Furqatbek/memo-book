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
