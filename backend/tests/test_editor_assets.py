"""Every local asset the editor references actually exists.

The editor is a no-build frontend: nothing resolves its imports, nothing
fingerprints its filenames, and nothing fails at compile time. A renamed
illustration or a mistyped `?v=` stamp is a 404 at runtime, and the failure
is quiet in the worst way — the page still renders, just without its
background, its font, or the module that wires up a button.

So: read the markup and the stylesheet, collect every same-origin URL they
name, and check the file is on disk. Derived from the files themselves, so a
new `<script src>` or `url()` is covered the moment it is written.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EDITOR = REPO / "editor"

# Same-origin only: anything with a scheme, a protocol-relative prefix, a
# fragment or a data payload is not ours to find on disk.
EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|#|\?)", re.I)


def _local(url: str) -> str | None:
    url = url.strip().strip("'\"")
    if not url or EXTERNAL.match(url):
        return None
    return url.split("?", 1)[0].split("#", 1)[0]


def html_references() -> set[str]:
    html = (EDITOR / "index.html").read_text(encoding="utf-8")
    urls = re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', html)
    # Dynamic `import('./js/x.js?v=1')` in inline scripts counts too.
    urls += re.findall(r"""import\(\s*['"]([^'"]+)['"]""", html)
    return {u for u in map(_local, urls) if u}


def css_references() -> set[str]:
    css = (EDITOR / "editor.css").read_text(encoding="utf-8")
    return {u for u in map(_local, re.findall(r"url\(([^)]+)\)", css)) if u}


def js_module_imports() -> set[str]:
    """Relative specifiers in the editor's own ES modules."""
    out: set[str] = set()
    for js in sorted((EDITOR / "js").glob("*.js")):
        src = js.read_text(encoding="utf-8")
        for spec in re.findall(r"""(?:from|import)\s*\(?\s*['"](\.[^'"]+)['"]""", src):
            out.add(str((js.parent / _local(spec)).resolve().relative_to(EDITOR)))
    return out


@pytest.mark.parametrize("url", sorted(html_references()))
def test_markup_references_a_real_file(url):
    if url.startswith("/") or url.startswith(".."):
        pytest.skip(f"{url} is served by the site mount, not the editor mount")
    assert (EDITOR / url).exists(), f"editor/index.html references missing {url}"


@pytest.mark.parametrize("url", sorted(css_references()))
def test_stylesheet_references_a_real_file(url):
    assert (EDITOR / url).exists(), f"editor.css references missing {url}"


@pytest.mark.parametrize("path", sorted(js_module_imports()))
def test_module_imports_resolve(path):
    assert (EDITOR / path).exists(), f"an editor module imports missing {path}"


def test_cache_stamped_files_are_stamped_everywhere():
    """A61: markup and code revalidate, but the `?v=` stamps are what force a
    reload of a module the browser already holds. A stamp on one import of a
    file and not another means half the page runs old code."""
    html = (EDITOR / "index.html").read_text(encoding="utf-8")
    unstamped = [u for u in re.findall(r'(?:src|href)\s*=\s*"(\./js/[^"]+|js/[^"]+|editor\.css[^"]*)"', html)
                 if "?v=" not in u]
    assert not unstamped, f"unstamped code references in index.html: {unstamped}"
