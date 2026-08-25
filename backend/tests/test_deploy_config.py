"""A75: a fresh VPS must be reproducible from this repository alone.

The failure this guards against has already happened once: `ADMIN_TOKEN` was
never in `.env.prod.example`, so every fresh deploy came up with the admin
console permanently answering 404 — the fail-closed behaviour working exactly
as designed (A72), on a machine where nobody had been given the chance to set
the token. Nothing was broken; nothing said anything; the console simply did
not exist.

That class of bug is invisible to every other test in this suite, because
every other test constructs its own configuration. These read the deployment
files as a deployer would.
"""
import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent.parent
COMPOSE = REPO / "deploy" / "docker-compose.prod.yml"
ENV_EXAMPLE = REPO / "deploy" / ".env.prod.example"
BOOTSTRAP = REPO / "deploy" / "bootstrap.sh"
SETTINGS = REPO / "backend" / "app" / "config.py"


def env_keys() -> dict[str, str]:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    return dict(re.findall(r"^([A-Z0-9_]+)=(.*)$", text, re.M))


def settings_fields() -> set[str]:
    body = SETTINGS.read_text(encoding="utf-8").split("class Settings")[1]
    return {m.upper() for m in
            re.findall(r"^\s{4}(\w+):\s*[^=\n]+?\s*=", body, re.M)}


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


class TestEverySettingIsReachable:
    """Settings the deployer cannot reach are settings that keep their
    development defaults on a production machine forever."""

    # Set by docker-compose (paths inside the image, the internal storage
    # endpoint) or genuinely internal tuning nobody deploying needs to see.
    # Anything not listed here must be documented in .env.prod.example.
    NOT_FOR_THE_DEPLOYER = {
        "APP_NAME",
        "S3_ENDPOINT_URL",     # compose points this at the minio container
        "EDITOR_DIR", "ADMIN_DIR", "SITE_DIR",   # paths inside the image
        "READY_CHECK_TIMEOUT_S",
        "RATE_LIMIT_ADMIN_PER_MIN",
    }

    def test_no_setting_is_silently_unreachable(self):
        missing = settings_fields() - set(env_keys()) - self.NOT_FOR_THE_DEPLOYER
        assert not missing, (
            "these settings exist in config.py but appear nowhere in "
            f"deploy/.env.prod.example, so a deployer cannot set them: "
            f"{sorted(missing)}. Add them there, or to NOT_FOR_THE_DEPLOYER "
            "with a reason.")

    def test_the_exemption_list_has_no_ghosts(self):
        """A name that no longer exists in config.py is an exemption that
        stopped meaning anything."""
        stale = self.NOT_FOR_THE_DEPLOYER - settings_fields()
        assert not stale, f"no longer settings: {sorted(stale)}"

    def test_no_key_in_the_example_is_a_typo(self):
        """The other direction: a key the backend never reads does nothing,
        and looks exactly like one that works."""
        known = settings_fields() | {
            # Read by docker-compose itself, not by the app.
            "DOMAIN", "POSTGRES_PASSWORD", "MINIO_ROOT_USER",
            "MINIO_ROOT_PASSWORD", "STORAGE_CORS_ORIGINS",
        }
        unknown = set(env_keys()) - known
        assert not unknown, (
            f"keys nothing reads: {sorted(unknown)} — a typo here is silent")


class TestTheSecretsAreGenerated:
    def test_every_placeholder_is_filled_in_by_bootstrap(self):
        """A CHANGE_ME the bootstrap does not substitute reaches production
        as the literal string CHANGE_ME."""
        placeholders = set(re.findall(r"CHANGE_ME_\w+",
                                      ENV_EXAMPLE.read_text(encoding="utf-8")))
        script = BOOTSTRAP.read_text(encoding="utf-8")
        unhandled = [p for p in placeholders if f"s/{p}/" not in script]
        assert not unhandled, (
            f"bootstrap.sh never replaces {sorted(unhandled)}")

    def test_the_admin_token_is_one_of_them(self):
        """The specific hole this file was written for. An empty or
        placeholder ADMIN_TOKEN means no admin console at all (A72), and it
        fails silently — 404 is also what a wrong token returns."""
        assert env_keys().get("ADMIN_TOKEN", "").startswith("CHANGE_ME"), (
            "ADMIN_TOKEN must be a generated placeholder in "
            ".env.prod.example — blank ships a dead admin console")
        assert "ADMIN_TOKEN=$(openssl rand" in BOOTSTRAP.read_text(
            encoding="utf-8"), "bootstrap.sh must generate an admin token"


class TestTheStackSurvivesTheMachine:
    ONE_SHOT = {"minio-init"}

    def test_every_long_running_service_restarts_itself(self, compose):
        """After a reboot, or an OOM kill, nobody is watching."""
        for name, svc in compose["services"].items():
            if name in self.ONE_SHOT:
                continue
            assert svc.get("restart") == "unless-stopped", (
                f"{name} would stay down after a reboot")

    def test_a_one_shot_job_does_not_restart(self, compose):
        """minio-init exits 0 on purpose; restarting it forever would make
        `docker compose ps` permanently alarming."""
        for name in self.ONE_SHOT:
            assert "restart" not in compose["services"][name]

    def test_no_container_can_fill_the_disk_with_logs(self, compose):
        """Docker's default json-file driver has no size limit at all: one
        chatty container writes until the partition is full, and every other
        service then fails for a reason that looks nothing like logging."""
        for name, svc in compose["services"].items():
            if name in self.ONE_SHOT:
                continue
            opts = (svc.get("logging") or {}).get("options") or {}
            assert opts.get("max-size"), f"{name} has unbounded logs"
            assert opts.get("max-file"), f"{name} keeps unbounded log files"

    def test_the_database_is_not_exposed_to_the_internet(self, compose):
        """Only Caddy publishes ports; everything else is reachable on the
        compose network alone."""
        published = {n: s.get("ports") for n, s in compose["services"].items()
                     if s.get("ports")}
        assert set(published) == {"caddy"}, (
            f"these publish ports to the host: {sorted(published)}")


class TestBackupsAreRealOrAbsent:
    """A backup job that runs and stores nothing is worse than none: it is
    the same outcome plus confidence."""

    def test_the_backup_refuses_an_unconfigured_destination(self):
        script = (REPO / "deploy" / "backup.sh").read_text(encoding="utf-8")
        assert 'RESTIC_REPOSITORY:-' in script and "die" in script

    def test_the_dump_is_verified_before_it_is_stored(self):
        """`pg_restore --list` reads only the table of contents at the front
        of the archive and passes a dump that was cut off halfway. Decoding
        the whole thing is what actually catches truncation."""
        script = (REPO / "deploy" / "backup.sh").read_text(encoding="utf-8")
        assert "pg_restore -f /dev/null" in script

    def test_there_is_a_way_to_rehearse_a_restore(self):
        assert "--drill" in (REPO / "deploy" / "restore.sh").read_text(
            encoding="utf-8")
