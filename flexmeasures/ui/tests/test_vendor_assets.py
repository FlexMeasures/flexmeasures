"""The UI serves its third-party assets itself, so it also works without internet access."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
from flask import url_for
from jinja2.runtime import Macro

from flexmeasures.ui import flexmeasures_ui

UI_DIR = Path(flexmeasures_ui.root_path)
STATIC_DIR = UI_DIR / "static"
TEMPLATE_DIR = UI_DIR / "templates"

TAG_URL = re.compile(r"""(?:src|href)=["']([^"']+)["']""")
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


def test_js_versions_global_keeps_legacy_keys(app):
    """Plugin templates that read `js_versions.vega` and the like keep working."""
    from flexmeasures.ui.utils.vendor_versions import JS_VERSIONS

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


def test_every_vendored_asset_is_served(app, client):
    """Each macro in includes/vendor.html points at files that are served, so bumping a version without adding its files fails here."""
    with app.test_request_context():
        module = app.jinja_env.get_template("includes/vendor.html").module
        macros = [m for m in vars(module).values() if isinstance(m, Macro)]
        urls = {url for macro in macros for url in TAG_URL.findall(str(macro()))}

    assert len(macros) == 10
    assert urls
    for url in sorted(urls):
        assert url.startswith("/ui/static/vendor/"), url
        response = client.get(url)
        assert response.status_code == 200, url
        response.close()


@pytest.mark.parametrize(
    "css_file",
    sorted(STATIC_DIR.glob("vendor/**/*.css"))
    + [STATIC_DIR / "css" / "flexmeasures.css"],
    ids=lambda path: str(path.relative_to(STATIC_DIR)),
)
def test_css_references_resolve(css_file: Path):
    """Fonts and images that a stylesheet refers to by relative path exist next to it."""
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
    """No template or stylesheet makes the browser fetch scripts, styles, fonts or images from another host; plain links are fine."""
    offenders = []
    for path in [*TEMPLATE_DIR.rglob("*.html"), *(STATIC_DIR / "css").rglob("*.css")]:
        text = path.read_text()
        for match in EXTERNAL_ASSET.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(UI_DIR)}:{line}")
    assert offenders == []


def test_login_page_loads_vendored_assets(client):
    """Pages not rendered through render_flexmeasures_template, like the login page, also load the vendored assets."""
    page = client.get(url_for("security.login"))
    assert page.status_code == 200
    assert b"/ui/static/vendor/jquery/" in page.data
    assert b"/ui/static/vendor/bootstrap/" in page.data


def test_versioned_vendor_files_are_cached_long(client):
    """Browsers keep versioned vendor files for a year, so a page view on a poor connection does not re-check about 30 files."""
    from flexmeasures.ui.utils.vendor_versions import JS_VERSIONS

    response = client.get(
        f"/ui/static/vendor/jquery/{JS_VERSIONS['jquery']}/jquery.min.js"
    )
    assert response.status_code == 200
    assert response.cache_control.max_age == 31536000
    assert response.cache_control.immutable
    response.close()

    # Files without a version in their path keep Flask's default, so a changed file reaches browsers.
    response = client.get("/ui/static/vendor/poppins/v20/pxiEyp8kv8JHgFVrJJfecg.woff2")
    assert response.status_code == 200
    assert response.cache_control.max_age is None
    response.close()
