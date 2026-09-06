"""Tests for loading plugins, i.e. for the FLEXMEASURES_PLUGINS setting."""

from __future__ import annotations

import os
import sys

import pytest
from flask import Flask

from flexmeasures.utils.plugin_utils import register_plugins


def write_plugin(root, pkg_name: str, marker: str, with_init: bool = True):
    """Write a minimal plugin package, whose Blueprint gets its route from a submodule.

    This mirrors the common plugin layout: the Blueprint is created in ``__init__.py``,
    and ``views.py`` imports it to attach routes. The marker distinguishes two copies
    of the same plugin, and rides along on the module and its route.
    """
    pkg = root / pkg_name
    pkg.mkdir(parents=True)
    if not with_init:
        return pkg
    (pkg / "__init__.py").write_text(
        "from flask import Blueprint\n"
        f"MARKER = '{marker}'\n"
        f"__version__ = '{marker}'\n"
        f"bp = Blueprint('{pkg_name}_{marker}', __name__)\n"
        f"import {pkg_name}.views  # noqa: E402,F401 (attaches the routes to bp)\n"
    )
    (pkg / "views.py").write_text(
        f"from {pkg_name} import bp\n"
        "\n"
        f"@bp.route('/{marker}')\n"
        "def a_route():\n"
        f"    return '{marker}'\n"
    )
    return pkg


@pytest.fixture
def clean_import_state():
    """Undo the sys.path and sys.modules changes that loading a plugin makes."""
    original_path = list(sys.path)
    original_modules = dict(sys.modules)
    yield
    sys.path[:] = original_path
    for name in set(sys.modules) - set(original_modules):
        del sys.modules[name]
    sys.modules.update(original_modules)


def make_app(plugins: list[str]) -> Flask:
    app = Flask(__name__)
    app.config["FLEXMEASURES_PLUGINS"] = plugins
    return app


def test_installed_package_wins_from_folder_in_working_directory(
    tmp_path, monkeypatch, clean_import_state
):
    """A bare plugin name resolves to the installed package, not to a folder in the cwd.

    Regression test for GH issue #2415: loading the folder executed ``__init__.py`` a second
    time, so the routes that ``views.py`` had attached to the first Blueprint were lost, and
    the Blueprint that got registered was empty. Both copies here define a route, so the
    routing table tells us which module was loaded, and whether its routes survived.
    """
    installed = tmp_path / "site-packages"
    write_plugin(installed, "my_plugin", marker="installed")
    monkeypatch.syspath_prepend(str(installed))

    working_directory = tmp_path / "plugin-repo"
    write_plugin(working_directory, "my_plugin", marker="shadow")
    monkeypatch.chdir(working_directory)
    assert os.path.exists("my_plugin"), "the shadowing folder must be in the cwd"

    app = make_app(["my_plugin"])
    register_plugins(app)

    assert app.config["LOADED_PLUGINS"] == {"my_plugin": "installed"}
    assert sys.modules["my_plugin"].MARKER == "installed"
    routes = [str(rule) for rule in app.url_map.iter_rules()]
    assert "/installed" in routes, "the installed plugin's route must be registered"
    assert "/shadow" not in routes


def test_folder_in_working_directory_is_loaded_when_nothing_is_installed(
    tmp_path, monkeypatch, clean_import_state, caplog
):
    """Without an installed package of that name, a bare name still loads the cwd folder."""
    working_directory = tmp_path / "plugin-repo"
    write_plugin(working_directory, "lonely_plugin", marker="from-cwd")
    monkeypatch.chdir(working_directory)
    monkeypatch.syspath_prepend(str(working_directory))

    app = make_app(["lonely_plugin"])
    register_plugins(app)

    assert app.config["LOADED_PLUGINS"] == {"lonely_plugin": "from-cwd"}
    assert "/from-cwd" in [str(rule) for rule in app.url_map.iter_rules()]


def test_path_entry_still_loads_the_folder_it_points_to(
    tmp_path, monkeypatch, clean_import_state
):
    """Spelling out a path loads that folder, even when a package of that name is installed."""
    installed = tmp_path / "site-packages"
    write_plugin(installed, "my_plugin", marker="installed")
    monkeypatch.syspath_prepend(str(installed))

    working_directory = tmp_path / "plugin-repo"
    write_plugin(working_directory, "my_plugin", marker="by-path")
    monkeypatch.chdir(working_directory)

    app = make_app([f".{os.sep}my_plugin"])
    register_plugins(app)

    assert app.config["LOADED_PLUGINS"] == {"my_plugin": "by-path"}
    assert "/by-path" in [str(rule) for rule in app.url_map.iter_rules()]


def test_absolute_path_entry_loads_the_folder_it_points_to(
    tmp_path, monkeypatch, clean_import_state
):
    """An absolute path is a path, too, wherever the process happens to run from."""
    plugin = write_plugin(tmp_path / "elsewhere", "my_plugin", marker="absolute")
    monkeypatch.syspath_prepend(str(tmp_path / "elsewhere"))
    monkeypatch.chdir(tmp_path)

    app = make_app([str(plugin)])
    register_plugins(app)

    assert app.config["LOADED_PLUGINS"] == {"my_plugin": "absolute"}


def test_folder_without_init_file_reports_a_clear_error(
    tmp_path, monkeypatch, clean_import_state, caplog
):
    """A folder without __init__.py is importable as a namespace package, but we don't.

    Reporting the missing ``__init__.py`` is more useful than loading an empty namespace
    package and then complaining that it defines no Blueprints.
    """
    working_directory = tmp_path / "plugin-repo"
    write_plugin(working_directory, "no_init_plugin", marker="", with_init=False)
    monkeypatch.chdir(working_directory)
    monkeypatch.syspath_prepend(str(working_directory))

    app = make_app(["no_init_plugin"])
    with caplog.at_level("ERROR"):
        register_plugins(app)

    assert app.config["LOADED_PLUGINS"] == {}
    assert "does not contain an '__init__.py' file" in caplog.text


def test_missing_plugin_reports_that_it_is_not_installed(
    tmp_path, monkeypatch, clean_import_state, caplog
):
    """A name that is neither installed nor a folder is reported as not installed."""
    monkeypatch.chdir(tmp_path)

    app = make_app(["there_is_no_such_plugin"])
    with caplog.at_level("ERROR"):
        register_plugins(app)

    assert app.config["LOADED_PLUGINS"] == {}
    assert "it is not installed" in caplog.text


def test_register_plugins_error_hints_at_comma_separated_format(caplog):
    """Failing to import an unrecognised plugin should hint at the expected
    comma-separated format, so a malformed setting (e.g. a JSON array) doesn't
    read as a packaging problem."""
    app = Flask(__name__)
    app.config["FLEXMEASURES_PLUGINS"] = '["flexmeasures_entsoe"]'
    register_plugins(app)
    errors = [
        record.message
        for record in caplog.records
        if "comma-separated" in record.message
    ]
    assert errors
