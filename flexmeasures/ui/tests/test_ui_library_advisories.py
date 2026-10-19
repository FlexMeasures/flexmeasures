"""ci/check_ui_library_advisories.py looks up each of the UI's libraries under its npm name, and leaves out ignored advisories."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from flexmeasures.ui.utils.vendor_assets import VENDOR_LIBRARIES

SCRIPT = Path(__file__).resolve().parents[3] / "ci" / "check_ui_library_advisories.py"


@pytest.fixture
def check():
    spec = importlib.util.spec_from_file_location("check_ui_library_advisories", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_reads_the_libraries_without_importing_flexmeasures(check):
    """The workflow only installs Flask, so the script reads vendor_assets.py by path."""
    libraries = check.load_libraries()
    assert {key: library.version for key, library in libraries.items()} == {
        key: library.version for key, library in VENDOR_LIBRARIES.items()
    }


def test_libraries_are_looked_up_under_their_npm_names(check):
    """Libraries served from another CDN are looked up under their npm package, and fonts, which are not on npm, are skipped."""
    queried = []

    def query(packages):
        queried.extend(packages)
        return [[] for _ in packages]

    assert check.find_advisories(VENDOR_LIBRARIES, query=query) == []
    names = {name for name, _ in queried}
    assert {
        "vega",
        "jquery",
        "@json-editor/json-editor",
        "datatables.net",
        "datatables.net-plugins",
    } <= names
    assert "DataTables" not in names
    assert "Poppins" not in names
    assert len(queried) == len(VENDOR_LIBRARIES) - 1  # all but Poppins


def test_ignored_advisories_are_left_out(check, monkeypatch):
    """An advisory is only ignored for the package and version it was recorded for."""
    monkeypatch.setattr(
        check,
        "IGNORED",
        {("GHSA-1", "vega", VENDOR_LIBRARIES["vega"].version): "reason"},
    )

    def query(packages):
        return [
            ["GHSA-1", "GHSA-2"] if name in ("vega", "jquery") else []
            for name, _ in packages
        ]

    found = check.find_advisories(VENDOR_LIBRARIES, query=query)
    assert sorted((key, advisory) for key, _, _, advisory in found) == [
        ("jquery", "GHSA-1"),
        ("jquery", "GHSA-2"),
        ("vega", "GHSA-2"),
    ]
