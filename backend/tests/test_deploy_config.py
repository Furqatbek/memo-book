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


# ---------------------------------------------------------------- Caddyfile

CADDYFILE = REPO / "deploy" / "Caddyfile"


def caddy_site_blocks() -> dict[str, str]:
    """{address line: block body} for every site block in the Caddyfile.

    Read rather than assumed: the hostnames Caddy will actually try to get
    certificates for are the ones written here, and a name in the README that
    is not in this file is a name that never resolves.

    Scanned brace by brace rather than by regex, because a site address is
    itself `{$DOMAIN}, api.{$DOMAIN}`. For the same reason placeholders are
    masked first: `{$DOMAIN}` and `{uri}` are braces that open nothing, and
    counting them as depth walks straight off the end of the file.
    """
    text = re.sub(r"(?m)^\s*#.*$", "", CADDYFILE.read_text(encoding="utf-8"))
    masked = re.sub(r"\{\$?[A-Za-z_][\w.]*\}",
                    lambda m: "\x00" * len(m.group()), text)

    blocks: dict[str, str] = {}
    depth, address, body_start = 0, None, 0
    for i, ch in enumerate(masked):
        if ch == "{":
            if depth == 0:
                # Everything back to the previous line break is the address;
                # a global options block has none.
                head = text[:i].rstrip()
                address = head[head.rfind("\n") + 1:].strip()
                body_start = i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and address:
                blocks[address] = text[body_start:i]
    return blocks


def test_every_hostname_the_readme_promises_is_actually_served():
    """The README tells the deployer which DNS A records to create before the
    first boot. Let's Encrypt validates over HTTP, so a name that is served
    but undocumented never gets a record — and never gets a certificate."""
    served = set()
    for address in caddy_site_blocks():
        for host in (a.strip() for a in address.split(",")):
            served.add(host.replace("{$DOMAIN}", "YOUR_DOMAIN"))

    readme = (REPO / "deploy" / "README.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"`((?:[a-z]+\.)?YOUR_DOMAIN)`", readme))
    missing = served - documented
    assert not missing, (
        f"the Caddyfile serves {sorted(missing)} but deploy/README.md never "
        f"tells the deployer to create those DNS records")


def test_the_admin_console_has_its_own_hostname_and_keeps_the_api_intact():
    """A87: admin.DOMAIN serves the console the backend keeps at /admin.

    The rewrite that makes that work must not touch `/api/*`: the console
    talks to the API with absolute paths, and rewriting those into
    `/admin/api/...` would leave a page that loads and then does nothing.
    """
    blocks = caddy_site_blocks()
    address = next((a for a in blocks if a.startswith("admin.{$DOMAIN}")), None)
    assert address, f"no admin.{{$DOMAIN}} block; found {sorted(blocks)}"

    body = blocks[address]
    assert re.search(r"handle\s+/api/\*\s*\{", body), (
        "admin.DOMAIN must route /api/* straight to the backend, before the "
        "rewrite — otherwise every call the console makes 404s")
    assert "rewrite * /admin{uri}" in body, (
        "the console lives at /admin on the backend and must be rewritten "
        "there, carrying {uri} so the ?v= cache stamps survive (A61)")
    # The /api/* handler has to come first: `handle` blocks are evaluated in
    # source order and the catch-all would otherwise swallow everything.
    assert body.index("/api/*") < body.index("rewrite * /admin{uri}")


def test_the_main_domain_still_serves_the_console_too():
    """The subdomain is a second door, not a move. Docs, ASSUMPTIONS and any
    bookmark still point at DOMAIN/admin/, which is a path on the main host
    and must not be redirected away."""
    blocks = caddy_site_blocks()
    main = next(a for a in blocks if a.startswith("{$DOMAIN}"))
    assert "reverse_proxy api:8000" in blocks[main]
    assert "/admin" not in blocks[main], (
        "the main host must pass /admin/ through to the backend untouched")
