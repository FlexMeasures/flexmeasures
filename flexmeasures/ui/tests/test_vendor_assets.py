"""The UI loads its third-party libraries from FlexMeasures when they were fetched, and from their CDNs otherwise."""

from __future__ import annotations

import ast
import base64
import hashlib
import logging
import re
from pathlib import Path

import pytest
import urllib.error
from flask import url_for
from jinja2.runtime import Macro

from flexmeasures.ui import (
    add_jinja_variables,
    flexmeasures_ui,
    load_vendor_libraries,
    log_where_vendor_files_load_from,
)
from flexmeasures.ui.utils import fetch_vendor_assets, vendor_assets
from flexmeasures.ui.utils.vendor_assets import (
    APP_EXTENSION,
    JS_VERSIONS,
    VENDOR_LIBRARIES,
    VendorLibrary,
    libraries_with_overrides,
)

UI_DIR = Path(flexmeasures_ui.root_path)
STATIC_DIR = UI_DIR / "static"
TEMPLATE_DIR = UI_DIR / "templates"

TAG = re.compile(r"""<(?:script|link)\b[^>]*>""")
TAG_URL = re.compile(r"""(?:src|href)="([^"]+)\"""")
INTEGRITY = re.compile(r"""integrity="([^"]+)\"""")
CSS_URL = re.compile(r"""url\(\s*["']?([^"')]+?)["']?\s*\)""")

HASH = "ab" * 32

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


def manifest_entry(
    url: str, libraries: dict[str, VendorLibrary] = VENDOR_LIBRARIES
) -> tuple[str, str]:
    """The library key and file path that a CDN URL was made from."""
    for key, library in libraries.items():
        for path in library.files:
            if library.url(path) == url:
                return key, path
    raise AssertionError(f"{url} is not in the libraries")


@pytest.fixture
def js_versions_setting(app, monkeypatch):
    """Start the app as with a FLEXMEASURES_JS_VERSIONS setting, and restore it afterwards."""
    monkeypatch.setitem(app.extensions, APP_EXTENSION, VENDOR_LIBRARIES)
    monkeypatch.setitem(app.jinja_env.globals, "js_versions", JS_VERSIONS)

    def set_setting(setting: dict):
        monkeypatch.setitem(app.config, "FLEXMEASURES_JS_VERSIONS", setting)
        load_vendor_libraries(app)
        add_jinja_variables(app)
        return app.extensions[APP_EXTENSION]

    return set_setting


def test_js_versions_global_keeps_legacy_keys(app):
    """Plugin templates that read `js_versions.vega` and the like keep working."""
    assert app.jinja_env.globals["js_versions"] == JS_VERSIONS
    assert LEGACY_KEYS <= JS_VERSIONS.keys()


def test_js_versions_global_follows_the_setting(app, js_versions_setting):
    """Plugin templates read the versions that the host set."""
    js_versions_setting({"vega": "9.9.9"})
    assert app.jinja_env.globals["js_versions"]["vega"] == "9.9.9"
    assert app.jinja_env.globals["js_versions"]["jquery"] == JS_VERSIONS["jquery"]


@pytest.mark.parametrize(
    "setting, expected_files",
    [
        # A copy of the setting's old defaults keeps the recorded hashes.
        ({"vega": JS_VERSIONS["vega"]}, VENDOR_LIBRARIES["vega"].files),
        ({"vega": "9.9.9"}, {"build/vega.min.js": None}),
        ({"vega": ("9.9.9", HASH)}, {"build/vega.min.js": HASH}),
        (
            {
                "leaflet": (
                    "9.9.9",
                    dict.fromkeys(VENDOR_LIBRARIES["leaflet"].files, HASH),
                )
            },
            dict.fromkeys(VENDOR_LIBRARIES["leaflet"].files, HASH),
        ),
    ],
)
def test_js_versions_setting_forms(setting, expected_files):
    """A version can be set on its own, with the hash of a library's one file, or with the hash of each of its files."""
    ((key, value),) = setting.items()
    library = libraries_with_overrides(setting)[key]
    assert library.version == (value if isinstance(value, str) else value[0])
    assert library.files == expected_files
    if library.version != VENDOR_LIBRARIES[key].version:
        assert library.license_sha256 is None


def test_js_versions_setting_ignores_unknown_libraries(caplog):
    with caplog.at_level(logging.WARNING):
        libraries = libraries_with_overrides({"vegga": "9.9.9"})
    assert libraries == VENDOR_LIBRARIES
    assert "FLEXMEASURES_JS_VERSIONS sets vegga" in caplog.text


@pytest.mark.parametrize(
    "setting, message",
    [
        ({"leaflet": ("9.9.9", HASH)}, "has 7 files"),
        ({"leaflet": ("9.9.9", {"dist/leaflet.css": HASH})}, "needs them for exactly"),
        ({"vega": ("9.9.9", "sha256-abc")}, "not a SHA-256 hash"),
        ({"vega": ("9.9.9",)}, "Set a version"),
        ({"vega": ("9.9.9", 5)}, "Set a version"),
        ({"vega": 5}, "Set a version"),
    ],
)
def test_js_versions_setting_rejects_unusable_hashes(setting, message):
    """A setting whose hashes cannot be matched to the library's files stops the app from starting, rather than loading files unchecked."""
    with pytest.raises(ValueError, match=message):
        libraries_with_overrides(setting)


def test_overridden_versions_load_from_cdns(app, not_fetched, js_versions_setting):
    """A version set without hashes loads unchecked, and one set with a hash is checked against it."""
    js_versions_setting({"vega": "9.9.9", "jquery": ("9.9.9", HASH)})
    _, html = render_vendor_macros(app)
    tags = {
        TAG_URL.findall(tag)[0]: tag for tag in TAG.findall(html) if TAG_URL.search(tag)
    }

    vega_tag = tags["https://cdn.jsdelivr.net/npm/vega@9.9.9/build/vega.min.js"]
    assert "integrity=" not in vega_tag
    jquery_tag = tags["https://cdn.jsdelivr.net/npm/jquery@9.9.9/dist/jquery.min.js"]
    digest = base64.b64encode(bytes.fromhex(HASH)).decode()
    assert f'integrity="sha256-{digest}"' in jquery_tag


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
        if url not in contents:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return contents[url]

    return contents, downloads, download


def test_fetch_stores_files_and_licence(not_fetched, fake_library):
    """Fetching stores a library's files and licence, and skips files that are already there."""
    contents, downloads, download = fake_library
    libraries = vendor_assets.VENDOR_LIBRARIES

    assert vendor_assets.fetch(download=download, libraries=libraries) == 3
    assert (
        vendor_assets.local_file("lib", "dist/lib.js", libraries).read_bytes() == b"lib"
    )
    assert (
        vendor_assets.local_file("lib", "dist/lib.css", libraries).read_bytes()
        == b"style"
    )
    assert (
        vendor_assets.local_file("lib", "LICENSE", libraries).read_bytes() == b"licence"
    )
    assert vendor_assets.missing_files(libraries) == []

    downloads.clear()
    assert vendor_assets.fetch(download=download, libraries=libraries) == 0
    assert downloads == []


def test_fetch_rejects_a_file_that_does_not_match_its_hash(not_fetched, fake_library):
    """A file whose content differs from what was recorded is not stored, and fetching fails."""
    contents, _, download = fake_library
    contents["https://cdn.example/lib@1.0/dist/lib.css"] = b"tampered"
    libraries = vendor_assets.VENDOR_LIBRARIES

    with pytest.raises(ValueError, match="does not match the hash"):
        vendor_assets.fetch(download=download, libraries=libraries)
    assert not vendor_assets.local_file("lib", "dist/lib.css", libraries).exists()
    assert not list(vendor_assets.VENDOR_DIR.rglob("*.part"))


def test_fetch_stores_an_overridden_version_with_hashes(
    not_fetched, fake_library, caplog
):
    """A version set with hashes is fetched and checked, while its licence, which is not executed, is fetched unchecked, and may be missing."""
    contents, _, download = fake_library
    contents["https://cdn.example/lib@2.0/dist/lib.js"] = b"lib 2"
    contents["https://cdn.example/lib@2.0/dist/lib.css"] = b"style 2"
    libraries = libraries_with_overrides(
        {
            "lib": (
                "2.0",
                {
                    "dist/lib.js": hashlib.sha256(b"lib 2").hexdigest(),
                    "dist/lib.css": hashlib.sha256(b"style 2").hexdigest(),
                },
            )
        }
    )

    with caplog.at_level(logging.WARNING):
        assert vendor_assets.fetch(download=download, libraries=libraries) == 2
    assert (
        vendor_assets.local_file("lib", "dist/lib.js", libraries).read_bytes()
        == b"lib 2"
    )
    assert "Could not fetch the licence of lib 2.0" in caplog.text

    contents["https://cdn.example/lib@2.0/dist/lib.css"] = b"tampered"
    vendor_assets.local_file("lib", "dist/lib.css", libraries).unlink()
    with pytest.raises(ValueError, match="does not match the hash"):
        vendor_assets.fetch(download=download, libraries=libraries)


def test_fetch_skips_an_overridden_version_without_hashes(not_fetched, fake_library):
    """A version set without hashes is never stored, so FlexMeasures does not serve unchecked files."""
    _, downloads, download = fake_library
    libraries = libraries_with_overrides({"lib": "2.0"})

    assert vendor_assets.fetch(download=download, libraries=libraries) == 0
    assert downloads == []
    assert vendor_assets.missing_files(libraries) == []
    assert vendor_assets.unhashed_libraries(libraries) == ["lib"]


@pytest.mark.parametrize("version", [None, "2.0"])
def test_print_hashes(fake_library, capsys, version):
    """Hashes are printed for VENDOR_LIBRARIES at the recorded version, and as a setting entry at another version."""
    contents, _, download = fake_library
    contents["https://cdn.example/lib@2.0/dist/lib.js"] = b"lib 2"
    contents["https://cdn.example/lib@2.0/dist/lib.css"] = b"style 2"

    vendor_assets.print_hashes("lib", download=download, version=version)
    printed = capsys.readouterr().out
    if version is None:
        assert f'"dist/lib.js": "{hashlib.sha256(b"lib").hexdigest()}",' in printed
        assert printed.startswith("files={")
    else:
        assert printed.startswith('"lib": ("2.0", {')
        assert f'"dist/lib.js": "{hashlib.sha256(b"lib 2").hexdigest()}",' in printed
        # What is printed is a valid entry of the setting.
        setting = ast.literal_eval("{" + printed + "}")
        assert libraries_with_overrides(setting)["lib"].files == {
            "dist/lib.js": hashlib.sha256(b"lib 2").hexdigest(),
            "dist/lib.css": hashlib.sha256(b"style 2").hexdigest(),
        }


def test_fetch_command_reads_the_setting_from_the_config_file(tmp_path, monkeypatch):
    """The fetch command fetches the versions which the host set in the config file."""
    config_file = tmp_path / "flexmeasures.cfg"
    config_file.write_text(
        'FLEXMEASURES_JS_VERSIONS = {"vega": ("9.9.9", "' + HASH + '")}\n'
    )
    fetched_with = {}

    def fake_fetch(keys, libraries):
        fetched_with.update(libraries)
        return 0

    monkeypatch.setattr(vendor_assets, "fetch", fake_fetch)
    assert fetch_vendor_assets.main(["--config", str(config_file)]) == 0
    assert fetched_with["vega"].version == "9.9.9"
    assert fetched_with["vega"].files == {"build/vega.min.js": HASH}

    with pytest.raises(SystemExit):
        fetch_vendor_assets.main(["--config", str(tmp_path / "missing.cfg")])


def test_startup_log_warns_about_versions_set_without_hashes(
    app, caplog, not_fetched, js_versions_setting
):
    """Hosts hear which libraries browsers load unchecked, and how to get their hashes."""
    js_versions_setting({"vega": "9.9.9"})
    with caplog.at_level(logging.WARNING):
        log_where_vendor_files_load_from(app)
    assert "--print-hashes vega --version 9.9.9" in caplog.text


@pytest.mark.parametrize("fetch_first", [False, True])
def test_startup_log_says_where_libraries_load_from(app, caplog, request, fetch_first):
    """Hosts hear that browsers load the libraries from CDNs, and how to change that, unless they fetched them."""
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


def test_fetched_files_of_an_overridden_version_are_cached_long(
    client, fetched, js_versions_setting
):
    """A version set through FLEXMEASURES_JS_VERSIONS gets its own path, so its files are cached long too."""
    libraries = js_versions_setting({"jquery": ("9.9.9", HASH)})
    file = vendor_assets.local_file("jquery", "dist/jquery.min.js", libraries)
    file.parent.mkdir(parents=True)
    file.write_text("jquery 9.9.9")

    response = client.get("/ui/static/vendor/jquery/9.9.9/dist/jquery.min.js")
    assert response.status_code == 200
    assert response.cache_control.max_age == 31536000
    response.close()


def test_unversioned_files_keep_default_caching(client):
    """Files without a version in their path keep Flask's default, so a changed file reaches browsers."""
    response = client.get("/ui/static/icons/mdi/battery.svg")
    assert response.status_code == 200
    assert response.cache_control.max_age is None
    response.close()


@pytest.fixture
def web_app(not_fetched):
    """A bare app on which FlexMeasures' fetching on the first request is set up, so tests can count its fetches."""
    from flask import Flask

    from flexmeasures.ui import fetch_vendor_files_on_first_request

    def make(fetch_setting: bool = True):
        web_app = Flask("web_app_under_test")
        web_app.config["FLEXMEASURES_FETCH_UI_LIBRARIES"] = fetch_setting
        web_app.extensions[APP_EXTENSION] = VENDOR_LIBRARIES
        web_app.add_url_rule("/", "index", lambda: "page")
        fetch_vendor_files_on_first_request(web_app)
        return web_app

    return make


@pytest.fixture
def blocking_fetch(monkeypatch):
    """Replace fetching with one that waits until the test releases it, and counts how often it was started."""
    import threading

    started = threading.Semaphore(0)
    release = threading.Event()
    calls = []

    def fake_fetch(libraries):
        calls.append(libraries)
        started.release()
        release.wait(timeout=5)
        return 3

    monkeypatch.setattr("flexmeasures.ui.fetch_unless_fetching", fake_fetch)
    yield started, release, calls
    release.set()


def test_first_request_fetches_in_the_background(web_app, blocking_fetch):
    """The first request starts fetching, without waiting for it, and later requests do not fetch again."""
    started, release, calls = blocking_fetch
    app_ = web_app()
    client_ = app_.test_client()

    # The fetch is still blocked, so getting a response shows that the request did not wait for it.
    assert client_.get("/").data == b"page"
    assert app_.extensions["flexmeasures_vendor_fetch"].is_alive()
    assert started.acquire(timeout=10)
    assert client_.get("/").data == b"page"
    release.set()
    app_.extensions["flexmeasures_vendor_fetch"].join(timeout=10)
    assert len(calls) == 1


def test_no_fetching_when_switched_off(web_app, blocking_fetch):
    _, _, calls = blocking_fetch
    app_ = web_app(fetch_setting=False)
    assert app_.test_client().get("/").data == b"page"
    assert "flexmeasures_vendor_fetch" not in app_.extensions
    assert calls == []


def test_failed_background_fetch_is_logged(web_app, monkeypatch, caplog):
    """A server without internet access logs that it could not fetch, and keeps serving pages."""

    def failing_fetch(libraries):
        raise urllib.error.URLError("no internet")

    monkeypatch.setattr("flexmeasures.ui.fetch_unless_fetching", failing_fetch)
    app_ = web_app()
    with caplog.at_level(logging.WARNING):
        assert app_.test_client().get("/").data == b"page"
        app_.extensions["flexmeasures_vendor_fetch"].join(timeout=10)
    assert "Could not fetch the UI's libraries" in caplog.text


@pytest.mark.skipif(vendor_assets.fcntl is None, reason="file locks need fcntl")
def test_only_one_process_fetches(not_fetched, fake_library):
    """While one process holds the lock, another process does not fetch, and fetches once the lock is free."""
    import fcntl

    _, downloads, download = fake_library
    libraries = vendor_assets.VENDOR_LIBRARIES
    vendor_assets.VENDOR_DIR.mkdir(parents=True)
    # Another open file description of the lock file conflicts with the one held here, as one in another process would.
    with open(vendor_assets.VENDOR_DIR / vendor_assets.LOCK_FILE, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert vendor_assets.fetch_unless_fetching(libraries, download) is None
        assert downloads == []
    assert vendor_assets.fetch_unless_fetching(libraries, download) == 3
    # Once nothing is missing, the lock is not even taken.
    with open(vendor_assets.VENDOR_DIR / vendor_assets.LOCK_FILE, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert vendor_assets.fetch_unless_fetching(libraries, download) == 0


@pytest.mark.parametrize("fetched_earlier", [False, True])
def test_startup_log_warns_when_fetched_files_went_missing(
    app, caplog, monkeypatch, not_fetched, fetched_earlier
):
    """When FlexMeasures does not fetch, a host who fetched before but misses files now, most likely after an upgrade, is warned."""
    monkeypatch.setitem(app.config, "FLEXMEASURES_FETCH_UI_LIBRARIES", False)
    if fetched_earlier:
        old_file = vendor_assets.VENDOR_DIR / "vega" / "5.0.0" / "build" / "vega.min.js"
        old_file.parent.mkdir(parents=True)
        old_file.write_text("vega 5.0.0")

    with caplog.at_level(logging.INFO):
        log_where_vendor_files_load_from(app)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "run: python -m flexmeasures.ui.utils.fetch_vendor_assets" in caplog.text
    assert bool(warnings) is fetched_earlier


def test_startup_log_says_fetching_follows(app, caplog, monkeypatch, not_fetched):
    monkeypatch.setitem(app.config, "FLEXMEASURES_FETCH_UI_LIBRARIES", True)
    with caplog.at_level(logging.INFO):
        log_where_vendor_files_load_from(app)
    assert (
        "fetches them in the background once it serves its first request" in caplog.text
    )
