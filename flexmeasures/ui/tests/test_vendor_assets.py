"""The UI loads its third-party libraries from FlexMeasures when they were fetched, and from their CDNs otherwise."""

from __future__ import annotations

import base64
import hashlib
import logging
import re
from pathlib import Path

import pytest
from flask import url_for
from jinja2.runtime import Macro

from flexmeasures.ui import flexmeasures_ui
from flexmeasures.ui.utils import vendor_assets
from flexmeasures.ui.utils.vendor_assets import (
    JS_VERSIONS,
    VENDOR_LIBRARIES,
    VendorLibrary,
)

UI_DIR = Path(flexmeasures_ui.root_path)
STATIC_DIR = UI_DIR / "static"
TEMPLATE_DIR = UI_DIR / "templates"

TAG = re.compile(r"""<(?:script|link)\b[^>]*>""")
TAG_URL = re.compile(r"""(?:src|href)="([^"]+)\"""")
INTEGRITY = re.compile(r"""integrity="([^"]+)\"""")
CSS_URL = re.compile(r"""url\(\s*["']?([^"')]+?)["']?\s*\)""")

LEGACY_KEYS = {
    "vega",
    "vegaembed",
    "vegalite",
    "echarts",
    "currencysymbolmap",
    "jsoneditor",
    "leaflet",
    "leafletmarkercluster",
    "leafletmarkerclusterlayersupport",
}


@pytest.fixture
def not_fetched(tmp_path, monkeypatch):
    """No library files were fetched, as in a fresh checkout or a pip-installed FlexMeasures."""
    monkeypatch.setattr(vendor_assets, "VENDOR_DIR", tmp_path / "vendor")


@pytest.fixture
def fetched(tmp_path, monkeypatch):
    """Every library file was fetched, as in the Docker image.

    The files hold placeholder content, as these tests are about where files load from, not what is in them.
    """
    static_dir = tmp_path / "static"
    monkeypatch.setattr(vendor_assets, "VENDOR_DIR", static_dir / "vendor")
    monkeypatch.setattr(flexmeasures_ui, "static_folder", str(static_dir))
    for key, library in VENDOR_LIBRARIES.items():
        for path in [*library.files, library.license_path]:
            file = vendor_assets.local_file(key, path)
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(f"{key} {path}")


def render_vendor_macros(app) -> tuple[list[Macro], str]:
    with app.test_request_context():
        module = app.jinja_env.get_template("includes/vendor.html").module
        macros = [m for m in vars(module).values() if isinstance(m, Macro)]
        return macros, "".join(str(macro()) for macro in macros)


def manifest_entry(url: str) -> tuple[str, str]:
    """The library key and file path that a CDN URL was made from."""
    for key, library in VENDOR_LIBRARIES.items():
        for path in library.files:
            if library.url(path) == url:
                return key, path
    raise AssertionError(f"{url} is not in VENDOR_LIBRARIES")


def test_js_versions_global_keeps_legacy_keys(app):
    """Plugin templates that read `js_versions.vega` and the like keep working."""
    assert app.jinja_env.globals["js_versions"] is JS_VERSIONS
    assert LEGACY_KEYS <= JS_VERSIONS.keys()


@pytest.mark.parametrize(
    "setting, expect_warning",
    [
        (None, False),
        ({"vega": "5.0.0"}, True),
    ],
)
def test_deprecated_js_versions_setting_is_warned_about(
    app, monkeypatch, caplog, setting, expect_warning
):
    """Hosts who still pin UI library versions hear that this setting is ignored now."""
    from flexmeasures.ui import warn_about_deprecated_js_versions

    if setting is None:
        monkeypatch.delitem(app.config, "FLEXMEASURES_JS_VERSIONS", raising=False)
    else:
        monkeypatch.setitem(app.config, "FLEXMEASURES_JS_VERSIONS", setting)

    with caplog.at_level(logging.WARNING):
        warn_about_deprecated_js_versions(app)

    warned = "FLEXMEASURES_JS_VERSIONS is deprecated" in caplog.text
    assert warned is expect_warning


def test_libraries_load_from_cdns_with_integrity_when_not_fetched(app, not_fetched):
    """Without fetched files, each tag loads its file from the library's CDN, and lets the browser check it against the recorded hash."""
    macros, html = render_vendor_macros(app)
    tags = [
        tag for tag in TAG.findall(html) if TAG_URL.search(tag)
    ]  # leave out inline scripts

    assert len(macros) == 10
    assert tags
    for tag in tags:
        (url,) = TAG_URL.findall(tag)
        key, path = manifest_entry(url)
        digest = bytes.fromhex(VENDOR_LIBRARIES[key].files[path])
        assert INTEGRITY.findall(tag) == [
            f"sha256-{base64.b64encode(digest).decode()}"
        ], tag
        assert 'crossorigin="anonymous"' in tag, tag
    # Fonts and images in the inline styles come from CDNs too.
    for url in CSS_URL.findall(html):
        manifest_entry(url)


def test_libraries_load_from_flexmeasures_when_fetched(app, client, fetched):
    """With fetched files, each tag and inline style loads its file from FlexMeasures, which serves it."""
    _, html = render_vendor_macros(app)
    urls = TAG_URL.findall(html) + CSS_URL.findall(html)

    assert "integrity=" not in html
    assert urls
    for url in sorted(set(urls)):
        assert url.startswith("/ui/static/vendor/"), url
        response = client.get(url)
        assert response.status_code == 200, url
        response.close()


def test_login_page_loads_libraries(client, not_fetched):
    """Pages not rendered through render_flexmeasures_template, like the login page, also load the libraries."""
    page = client.get(url_for("security.login"))
    assert page.status_code == 200
    assert b"https://cdn.jsdelivr.net/npm/jquery@" in page.data
    assert b"https://cdn.jsdelivr.net/npm/bootstrap@" in page.data


@pytest.fixture
def fake_library(monkeypatch):
    """A library with two files and a licence, whose downloads are served from memory."""
    contents = {
        "https://cdn.example/lib@1.0/dist/lib.js": b"lib",
        "https://cdn.example/lib@1.0/dist/lib.css": b"style",
        "https://cdn.example/lib@1.0/LICENSE": b"licence",
    }
    library = VendorLibrary(
        name="lib",
        version="1.0",
        base_url="https://cdn.example/{name}@{version}/",
        files={
            "dist/lib.js": hashlib.sha256(b"lib").hexdigest(),
            "dist/lib.css": hashlib.sha256(b"style").hexdigest(),
        },
        license="LICENSE",
        license_sha256=hashlib.sha256(b"licence").hexdigest(),
    )
    monkeypatch.setattr(vendor_assets, "VENDOR_LIBRARIES", {"lib": library})
    downloads = []

    def download(url: str) -> bytes:
        downloads.append(url)
        return contents[url]

    return contents, downloads, download


def test_fetch_stores_files_and_licence(not_fetched, fake_library):
    """Fetching stores a library's files and licence, and skips files that are already there."""
    contents, downloads, download = fake_library

    assert vendor_assets.fetch(download=download) == 3
    assert vendor_assets.local_file("lib", "dist/lib.js").read_bytes() == b"lib"
    assert vendor_assets.local_file("lib", "dist/lib.css").read_bytes() == b"style"
    assert vendor_assets.local_file("lib", "LICENSE").read_bytes() == b"licence"
    assert vendor_assets.missing_files() == []

    downloads.clear()
    assert vendor_assets.fetch(download=download) == 0
    assert downloads == []


def test_fetch_rejects_a_file_that_does_not_match_its_hash(not_fetched, fake_library):
    """A file whose content differs from what was recorded is not stored, and fetching fails."""
    contents, _, download = fake_library
    contents["https://cdn.example/lib@1.0/dist/lib.css"] = b"tampered"

    with pytest.raises(ValueError, match="does not match the hash"):
        vendor_assets.fetch(download=download)
    assert not vendor_assets.local_file("lib", "dist/lib.css").exists()
    assert not list(vendor_assets.VENDOR_DIR.rglob("*.part"))


@pytest.mark.parametrize("fetch_first", [False, True])
def test_startup_log_says_where_libraries_load_from(app, caplog, request, fetch_first):
    """Hosts hear that browsers load the libraries from CDNs, and how to change that, unless they fetched them."""
    from flexmeasures.ui import log_where_vendor_files_load_from

    request.getfixturevalue("fetched" if fetch_first else "not_fetched")
    with caplog.at_level(logging.INFO):
        log_where_vendor_files_load_from(app)

    logged = "python -m flexmeasures.ui.utils.fetch_vendor_assets" in caplog.text
    assert logged is not fetch_first


@pytest.mark.parametrize(
    "css_file",
    sorted((STATIC_DIR / "css").rglob("*.css")),
    ids=lambda path: str(path.relative_to(STATIC_DIR)),
)
def test_css_references_resolve(css_file: Path):
    """Fonts and images that our own stylesheets refer to exist next to them."""
    for ref in CSS_URL.findall(css_file.read_text()):
        if ref.startswith(("data:", "#")):
            continue
        assert not re.match(r"https?://", ref), ref
        target = ref.split("?")[0].split("#")[0]
        assert (css_file.parent / target).resolve().is_file(), ref


EXTERNAL_ASSET = re.compile(
    r"""<(?:script|link|img)\b[^>]*?\s(?:src|href)=["']https?://"""
    r"""|url\(\s*["']?https?://"""
)


def test_no_external_asset_references():
    """No template or stylesheet names another host to fetch scripts, styles, fonts or images from, other than through VENDOR_LIBRARIES; plain links are fine."""
    offenders = []
    for path in [*TEMPLATE_DIR.rglob("*.html"), *(STATIC_DIR / "css").rglob("*.css")]:
        text = path.read_text()
        for match in EXTERNAL_ASSET.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(UI_DIR)}:{line}")
    assert offenders == []


def test_asset_type_icons_are_served(client):
    """The asset tree and asset lists show icons which FlexMeasures serves itself, rather than fetching them from iconify."""
    from flexmeasures.ui.utils.view_utils import FALLBACK_SVG_ICON, SVG_ICON_MAPPING

    for icon in sorted({*SVG_ICON_MAPPING.values(), FALLBACK_SVG_ICON}):
        assert icon.startswith("/ui/static/icons/"), icon
        response = client.get(icon)
        assert response.status_code == 200, icon
        assert response.mimetype == "image/svg+xml", icon
        response.close()


def test_fetched_files_are_cached_long(client, fetched):
    """Browsers keep fetched library files for a year, so a page view on a poor connection does not re-check about 30 files."""
    response = client.get(
        f"/ui/static/vendor/jquery/{JS_VERSIONS['jquery']}/dist/jquery.min.js"
    )
    assert response.status_code == 200
    assert response.cache_control.max_age == 31536000
    assert response.cache_control.immutable
    response.close()


def test_unversioned_files_keep_default_caching(client):
    """Files without a version in their path keep Flask's default, so a changed file reaches browsers."""
    response = client.get("/ui/static/icons/mdi/battery.svg")
    assert response.status_code == 200
    assert response.cache_control.max_age is None
    response.close()
