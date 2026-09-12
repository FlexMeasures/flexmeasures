"""Tests for loading plugins, i.e. for the FLEXMEASURES_PLUGINS setting, and for the settings a plugin declares."""

from __future__ import annotations

import importlib.util
import logging
import os
import sys

import pytest
from flask import Flask

from flexmeasures.utils.plugin_utils import check_config_settings, register_plugins


def write_plugin(root, pkg_name: str, marker: str, with_init: bool = True):
    """Write a minimal plugin package, whose Blueprint gets its route from a submodule.

    This mirrors the common plugin layout: the Blueprint is created in ``__init__.py``, and ``views.py`` imports it to attach routes.
    The marker distinguishes two copies of the same plugin, and rides along on the module and its route.
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
    """Undo the sys.path and sys.modules changes that loading a plugin makes.

    Only the modules a test added are dropped, so that unrelated imports in the same session are left alone.
    """
    original_path = list(sys.path)
    original_modules = set(sys.modules)
    yield
    sys.path[:] = original_path
    for name in set(sys.modules) - original_modules:
        del sys.modules[name]


def make_app(plugins: list[str]) -> Flask:
    app = Flask(__name__)
    app.config["FLEXMEASURES_PLUGINS"] = plugins
    return app


def test_installed_package_wins_from_folder_in_working_directory(
    tmp_path, monkeypatch, clean_import_state
):
    """A bare plugin name resolves to the installed package, not to a folder in the cwd.

    Regression test for GH issue #2415: loading the folder executed ``__init__.py`` a second time,
    so the routes that ``views.py`` had attached to the first Blueprint were lost, and the Blueprint that got registered was empty.
    Both copies here define a route, so the routing table tells us which module was loaded, and whether its routes survived.
    """
    installed = tmp_path / "site-packages"
    write_plugin(installed, "fm_test_plugin", marker="installed")
    monkeypatch.syspath_prepend(str(installed))

    working_directory = tmp_path / "plugin-repo"
    write_plugin(working_directory, "fm_test_plugin", marker="shadow")
    monkeypatch.chdir(working_directory)
    assert os.path.exists("fm_test_plugin"), "the shadowing folder must be in the cwd"

    app = make_app(["fm_test_plugin"])
    register_plugins(app)

    assert app.config["LOADED_PLUGINS"] == {"fm_test_plugin": "installed"}
    assert sys.modules["fm_test_plugin"].MARKER == "installed"
    routes = [str(rule) for rule in app.url_map.iter_rules()]
    assert "/installed" in routes, "the installed plugin's route must be registered"
    assert "/shadow" not in routes


def test_folder_in_working_directory_is_loaded_when_nothing_is_installed(
    tmp_path, monkeypatch, clean_import_state
):
    """Without another package of that name, a bare name still resolves to the folder in the cwd.

    The cwd is on ``sys.path`` here, as it is for a plugin repo one runs FlexMeasures from, so the folder is importable and loads as a package.
    """
    working_directory = tmp_path / "plugin-repo"
    write_plugin(working_directory, "fm_test_lonely_plugin", marker="from-cwd")
    monkeypatch.chdir(working_directory)
    monkeypatch.syspath_prepend(str(working_directory))

    app = make_app(["fm_test_lonely_plugin"])
    register_plugins(app)

    assert app.config["LOADED_PLUGINS"] == {"fm_test_lonely_plugin": "from-cwd"}
    assert "/from-cwd" in [str(rule) for rule in app.url_map.iter_rules()]


def test_a_bare_name_resolves_the_way_python_would_import_it(
    tmp_path, monkeypatch, clean_import_state
):
    """With the working directory ahead of site-packages on sys.path, the cwd copy is what gets imported.

    That is normal import resolution, and we deliberately do not fight it: forcing the installed copy here would give the process two module objects for one name,
    which is the very split that GH issue #2415 is about.
    What matters is that the folder is imported as a module, once, rather than executed a second time by path, so its routes survive either way.
    """
    installed = tmp_path / "site-packages"
    write_plugin(installed, "fm_test_plugin", marker="installed")

    working_directory = tmp_path / "plugin-repo"
    write_plugin(working_directory, "fm_test_plugin", marker="from-cwd")
    monkeypatch.chdir(working_directory)
    monkeypatch.syspath_prepend(str(installed))
    monkeypatch.syspath_prepend(
        str(working_directory)
    )  # as for `python -m`, the cwd comes first.

    app = make_app(["fm_test_plugin"])
    register_plugins(app)

    assert app.config["LOADED_PLUGINS"] == {"fm_test_plugin": "from-cwd"}
    routes = [str(rule) for rule in app.url_map.iter_rules()]
    assert "/from-cwd" in routes, "the routes of the imported copy must survive"
    assert "/installed" not in routes


def test_loading_a_cwd_folder_that_is_not_importable_warns(
    tmp_path, monkeypatch, clean_import_state, caplog
):
    """A bare name that only resolves to a folder in the cwd is loaded by path, with a warning.

    This is the one case the loader cannot tell apart from a mistyped package name, so it says what it did.
    """
    working_directory = tmp_path / "plugin-repo"
    write_plugin(working_directory, "fm_test_unimportable_plugin", marker="from-cwd")
    monkeypatch.chdir(working_directory)
    # Some runners put the working directory on sys.path, as "" or spelled out.
    # Both would make the plugin importable by name, which is the other branch.
    monkeypatch.setattr(
        sys,
        "path",
        [
            entry
            for entry in sys.path
            if entry not in ("", str(working_directory), os.curdir)
        ],
    )
    assert (
        importlib.util.find_spec("fm_test_unimportable_plugin") is None
    ), "this test is about the folder that cannot be imported by name"

    app = make_app(["fm_test_unimportable_plugin"])
    with caplog.at_level("WARNING"):
        register_plugins(app)

    assert app.config["LOADED_PLUGINS"] == {"fm_test_unimportable_plugin": "from-cwd"}
    assert (
        "Loading plugin fm_test_unimportable_plugin from the folder of that name in the working directory"
        in caplog.text
    ), "loading a folder for a bare name is ambiguous enough to warn about"


def test_path_entry_still_loads_the_folder_it_points_to(
    tmp_path, monkeypatch, clean_import_state
):
    """Spelling out a path loads that folder, even when a package of that name is installed."""
    installed = tmp_path / "site-packages"
    write_plugin(installed, "fm_test_plugin", marker="installed")
    monkeypatch.syspath_prepend(str(installed))

    working_directory = tmp_path / "plugin-repo"
    write_plugin(working_directory, "fm_test_plugin", marker="by-path")
    monkeypatch.chdir(working_directory)

    app = make_app([f".{os.sep}fm_test_plugin"])
    register_plugins(app)

    assert app.config["LOADED_PLUGINS"] == {"fm_test_plugin": "by-path"}
    assert "/by-path" in [str(rule) for rule in app.url_map.iter_rules()]


def test_absolute_path_entry_loads_the_folder_it_points_to(
    tmp_path, monkeypatch, clean_import_state
):
    """An absolute path is a path, too, wherever the process happens to run from."""
    plugin = write_plugin(tmp_path / "elsewhere", "fm_test_plugin", marker="absolute")
    monkeypatch.syspath_prepend(str(tmp_path / "elsewhere"))
    monkeypatch.chdir(tmp_path)

    app = make_app([str(plugin)])
    register_plugins(app)

    assert app.config["LOADED_PLUGINS"] == {"fm_test_plugin": "absolute"}


def test_folder_without_init_file_reports_a_clear_error(
    tmp_path, monkeypatch, clean_import_state, caplog
):
    """A folder without __init__.py is importable as a namespace package, but we don't.

    Reporting the missing ``__init__.py`` is more useful than loading an empty namespace package,
    and then complaining that it defines no Blueprints.
    """
    working_directory = tmp_path / "plugin-repo"
    write_plugin(
        working_directory, "fm_test_no_init_plugin", marker="", with_init=False
    )
    monkeypatch.chdir(working_directory)
    monkeypatch.syspath_prepend(str(working_directory))

    app = make_app(["fm_test_no_init_plugin"])
    with caplog.at_level("ERROR"):
        register_plugins(app)

    assert app.config["LOADED_PLUGINS"] == {}
    assert "does not contain an '__init__.py' file" in caplog.text


def test_missing_plugin_reports_that_it_is_not_installed(
    tmp_path, monkeypatch, clean_import_state, caplog
):
    """A name that is neither installed nor a folder is reported as not installed."""
    monkeypatch.chdir(tmp_path)

    app = make_app(["fm_test_there_is_no_such_plugin"])
    with caplog.at_level("ERROR"):
        register_plugins(app)

    assert app.config["LOADED_PLUGINS"] == {}
    assert "it is not installed" in caplog.text


def test_path_entry_with_a_trailing_separator_still_names_the_plugin(
    tmp_path, monkeypatch, clean_import_state
):
    """A path that ends in a separator names the folder it points to, not the empty string.

    Splitting the entry on "/" used to yield an empty plugin name here, which then became the module name and the LOADED_PLUGINS key.
    """
    write_plugin(tmp_path, "fm_test_plugin", marker="trailing")
    monkeypatch.chdir(tmp_path)

    app = make_app([f".{os.sep}fm_test_plugin{os.sep}"])
    register_plugins(app)

    assert app.config["LOADED_PLUGINS"] == {"fm_test_plugin": "trailing"}
    assert "/trailing" in [str(rule) for rule in app.url_map.iter_rules()]


def test_path_entry_that_does_not_exist_is_reported_as_a_missing_path(
    tmp_path, monkeypatch, clean_import_state, caplog
):
    """A path that does not exist is reported as such, rather than resolved as a package name.

    An installed package goes by the same name here, to show that spelling out a path rules it out.
    """
    installed = tmp_path / "site-packages"
    write_plugin(installed, "fm_test_plugin", marker="installed")
    monkeypatch.syspath_prepend(str(installed))
    monkeypatch.chdir(tmp_path / "site-packages")

    app = make_app([f"..{os.sep}nowhere{os.sep}fm_test_plugin"])
    with caplog.at_level("ERROR"):
        register_plugins(app)

    assert app.config["LOADED_PLUGINS"] == {}
    assert "does not exist" in caplog.text
    assert "/installed" not in [str(rule) for rule in app.url_map.iter_rules()]


def test_register_plugins_error_hints_at_comma_separated_format(caplog):
    """Failing to import an unrecognised plugin should hint at the expected comma-separated format,
    so that a malformed setting (e.g. a JSON array) does not read as a packaging problem.
    """
    app = Flask(__name__)
    app.config["FLEXMEASURES_PLUGINS"] = '["flexmeasures_entsoe"]'
    register_plugins(app)
    errors = [
        record.message
        for record in caplog.records
        if "comma-separated" in record.message
    ]
    assert errors


@pytest.fixture
def bare_app():
    """A minimal app to check plugin settings against, which is not in testing mode.

    Settings are only read from the environment outside of testing mode,
    just like FlexMeasures' own settings are.
    """
    app = Flask("test_plugin_settings")
    app.logger.setLevel(logging.DEBUG)
    return app


def test_setting_is_read_from_env(bare_app, monkeypatch, caplog):
    """A plugin setting that is only set in the environment ends up in the config."""
    monkeypatch.setenv("MY_PLUGIN_TOKEN", "token-from-env")
    with caplog.at_level(logging.ERROR):
        check_config_settings(bare_app, {"MY_PLUGIN_TOKEN": {"level": "error"}})
    assert bare_app.config["MY_PLUGIN_TOKEN"] == "token-from-env"
    assert "Missing config setting" not in caplog.text


def test_config_wins_over_env(bare_app, monkeypatch):
    """The config file is read before plugins are registered, so its value is kept."""
    monkeypatch.setenv("MY_PLUGIN_TOKEN", "token-from-env")
    bare_app.config["MY_PLUGIN_TOKEN"] = "token-from-config"
    check_config_settings(bare_app, {"MY_PLUGIN_TOKEN": {}})
    assert bare_app.config["MY_PLUGIN_TOKEN"] == "token-from-config"


def test_env_is_not_read_while_testing(monkeypatch):
    """Tests run on defaults, so they should not pick up settings from the environment."""
    monkeypatch.setenv("MY_PLUGIN_TOKEN", "token-from-env")
    app = Flask("test_plugin_settings")
    app.testing = True
    check_config_settings(app, {"MY_PLUGIN_TOKEN": {}})
    assert app.config.get("MY_PLUGIN_TOKEN") is None


def test_env_is_not_read_while_building_the_documentation(monkeypatch):
    """The documentation build runs on defaults, too."""
    monkeypatch.setenv("MY_PLUGIN_TOKEN", "token-from-env")
    app = Flask("test_plugin_settings")
    app.config["FLEXMEASURES_ENV"] = "documentation"
    check_config_settings(app, {"MY_PLUGIN_TOKEN": {}})
    assert app.config.get("MY_PLUGIN_TOKEN") is None


@pytest.mark.parametrize(
    "parse_as, env_value, expected_value",
    [
        (str, "some-string", "some-string"),
        (int, "42", 42),
        (float, "4.2", 4.2),
        (bool, "True", True),
        (bool, "0", False),
        (list, '["a", "b"]', ["a", "b"]),
        (dict, '{"a": 1}', {"a": 1}),
    ],
)
def test_env_value_is_parsed(
    bare_app, monkeypatch, parse_as, env_value, expected_value
):
    """Environment variables are strings, so they are read as the declared type."""
    monkeypatch.setenv("MY_PLUGIN_SETTING", env_value)
    check_config_settings(bare_app, {"MY_PLUGIN_SETTING": {"parse_as": parse_as}})
    assert bare_app.config["MY_PLUGIN_SETTING"] == expected_value
    assert isinstance(bare_app.config["MY_PLUGIN_SETTING"], parse_as)


def test_unparsable_env_value_is_reported(bare_app, monkeypatch, caplog):
    """A value we cannot read as the declared type is reported rather than swallowed."""
    monkeypatch.setenv("MY_PLUGIN_SETTING", "not-a-number")
    with caplog.at_level(logging.WARNING):
        check_config_settings(bare_app, {"MY_PLUGIN_SETTING": {"parse_as": int}})
    assert "Could not read config setting 'MY_PLUGIN_SETTING'" in caplog.text
    assert "is a <class 'str'> whereas a <class 'int'> was expected" in caplog.text


def test_missing_setting_without_default(bare_app, caplog):
    """The log message says the setting stays unset, even if the plugin suggests otherwise."""
    with caplog.at_level(logging.WARNING):
        check_config_settings(
            bare_app,
            {
                "MY_PLUGIN_COUNTRY": {
                    "description": "Country used by my plugin.",
                    "level": "warning",
                    "message_if_missing": "'NL' will be used as a default.",
                }
            },
        )
    assert (
        "Missing config setting 'MY_PLUGIN_COUNTRY' (Country used by my plugin.)."
        " 'NL' will be used as a default."
        " No default is declared for it, so it stays unset." in caplog.text
    )
    assert bare_app.config.get("MY_PLUGIN_COUNTRY") is None


def test_missing_setting_with_default(bare_app, caplog):
    """A declared default is applied, and named in the log message."""
    with caplog.at_level(logging.WARNING):
        check_config_settings(
            bare_app, {"MY_PLUGIN_COUNTRY": {"level": "warning", "default": "NL"}}
        )
    assert (
        "Missing config setting 'MY_PLUGIN_COUNTRY'."
        " Falling back to the default declared by the plugin: 'NL'." in caplog.text
    )
    assert bare_app.config["MY_PLUGIN_COUNTRY"] == "NL"


def test_default_of_the_wrong_type_is_reported(bare_app, caplog):
    """A default that does not match the declared type is reported, like any other value."""
    with caplog.at_level(logging.WARNING):
        check_config_settings(
            bare_app, {"MY_PLUGIN_TIMEOUT": {"parse_as": int, "default": "30"}}
        )
    assert "is a <class 'str'> whereas a <class 'int'> was expected" in caplog.text
    assert bare_app.config["MY_PLUGIN_TIMEOUT"] == "30"


def test_default_does_not_override_a_set_value(bare_app, monkeypatch, caplog):
    """A setting that is set is not touched, and is not reported as missing."""
    monkeypatch.setenv("MY_PLUGIN_COUNTRY", "BE")
    with caplog.at_level(logging.WARNING):
        check_config_settings(bare_app, {"MY_PLUGIN_COUNTRY": {"default": "NL"}})
    assert bare_app.config["MY_PLUGIN_COUNTRY"] == "BE"
    assert caplog.text == ""
