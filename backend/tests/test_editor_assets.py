"""Every local asset the two no-build frontends reference actually exists.

The editor and the admin console are both no-build frontends: nothing
resolves their imports, nothing fingerprints their filenames, and nothing
fails at compile time. A renamed illustration or a mistyped `?v=` stamp is a
404 at runtime, and the failure is quiet in the worst way — the page still
renders, just without its background, its font, or the module that wires up
a button.

So: read the markup, the stylesheets and the modules, collect every
same-origin URL they name, and check the file is on disk. Derived from the
files themselves, so a new `<script src>`, `url()` or `import` is covered the
moment it is written.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# (name, root, entry markup, stylesheets) for each no-build frontend.
APPS = [
    ("editor", REPO / "editor", "index.html", ["editor.css"]),
    ("admin", REPO / "admin", "index.html", ["admin.css"]),
]

# Same-origin only: anything with a scheme, a protocol-relative prefix, a
# fragment or a data payload is not ours to find on disk.
EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|#|\?)", re.I)


def _local(url: str) -> str | None:
    url = url.strip().strip("'\"")
    if not url or EXTERNAL.match(url):
        return None
    return url.split("?", 1)[0].split("#", 1)[0]


def _ids(case) -> str:
    return f"{case[0]}:{case[1]}"


def html_references() -> list[tuple[str, str, Path]]:
    out = []
    for name, root, entry, _ in APPS:
        html = (root / entry).read_text(encoding="utf-8")
        urls = re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', html)
        # Dynamic `import('./js/x.js?v=1')` in inline scripts counts too.
        urls += re.findall(r"""import\(\s*['"]([^'"]+)['"]""", html)
        for url in {u for u in map(_local, urls) if u}:
            out.append((name, url, root))
    return sorted(out)


def css_references() -> list[tuple[str, str, Path]]:
    out = []
    for name, root, _, sheets in APPS:
        for sheet in sheets:
            css = (root / sheet).read_text(encoding="utf-8")
            for url in {u for u in map(_local, re.findall(r"url\(([^)]+)\)", css)) if u}:
                out.append((f"{name}/{sheet}", url, root))
    return sorted(out)


def js_module_imports() -> list[tuple[str, str, Path]]:
    """Relative specifiers in each app's own ES modules."""
    out = []
    for name, root, _, _ in APPS:
        js_dir = root / "js"
        if not js_dir.is_dir():
            continue
        for js in sorted(js_dir.glob("*.js")):
            src = js.read_text(encoding="utf-8")
            for spec in re.findall(r"""(?:from|import)\s*\(?\s*['"](\.[^'"]+)['"]""", src):
                target = (js.parent / _local(spec)).resolve().relative_to(root)
                out.append((f"{name}/{js.name}", str(target), root))
    return sorted(set(out))


@pytest.mark.parametrize("case", html_references(), ids=_ids)
def test_markup_references_a_real_file(case):
    name, url, root = case
    if url.startswith("/") or url.startswith(".."):
        pytest.skip(f"{url} is served by the site mount, not the {name} mount")
    assert (root / url).exists(), f"{name}/index.html references missing {url}"


@pytest.mark.parametrize("case", css_references(), ids=_ids)
def test_stylesheet_references_a_real_file(case):
    name, url, root = case
    assert (root / url).exists(), f"{name} references missing {url}"


@pytest.mark.parametrize("case", js_module_imports(), ids=_ids)
def test_module_imports_resolve(case):
    name, path, root = case
    assert (root / path).exists(), f"{name} imports missing {path}"


@pytest.mark.parametrize("app", [a[0] for a in APPS])
def test_code_references_carry_a_cache_stamp(app):
    """A61: markup and code revalidate, but the `?v=` stamps are what force a
    reload of a module the browser already holds. An unstamped module is one
    a phone can hold for hours against freshly fetched markup — new buttons
    wired to code that is not there."""
    name, root, entry, sheets = next(a for a in APPS if a[0] == app)
    text = (root / entry).read_text(encoding="utf-8")
    sheet_pattern = "|".join(re.escape(s) for s in sheets)
    refs = re.findall(
        rf'(?:src|href)\s*=\s*"((?:\./)?js/[^"]+|(?:{sheet_pattern})[^"]*)"', text)
    # Every module import inside the modules themselves, too: app.js importing
    # an unstamped orders.js is the same stale-code trap one level down.
    for js in sorted((root / "js").glob("*.js")):
        refs += re.findall(
            r"""(?:from|import)\s*\(?\s*['"](\.[^'"]+\.m?js[^'"]*)['"]""",
            js.read_text(encoding="utf-8"))
    unstamped = [u for u in refs if "?v=" not in u]
    assert not unstamped, f"unstamped code references in {name}: {unstamped}"
