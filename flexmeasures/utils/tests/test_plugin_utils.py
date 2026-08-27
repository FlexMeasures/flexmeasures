import os
import sys
import types
import pytest
from flask import Flask, Blueprint

from flexmeasures.utils.plugin_utils import register_plugins


def test_installed_plugin_not_shadowed_by_cwd_folder(tmp_path, monkeypatch):
    """Test that an installed package is imported via import_module even if a folder with the same name exists in cwd."""
    pkg_name = "test_installed_plugin_shadow"

    # Create a mock installed module in sys.modules
    mock_module = types.ModuleType(pkg_name)
    mock_bp = Blueprint("installed_bp", pkg_name)
    mock_module.installed_bp = mock_bp
    mock_module.IS_INSTALLED = True
    mock_module.__version__ = "1.0.0"

    monkeypatch.setitem(sys.modules, pkg_name, mock_module)

    # Create a same-named folder in tmp_path with a dummy __init__.py
    plugin_dir = tmp_path / pkg_name
    plugin_dir.mkdir()
    (plugin_dir / "__init__.py").write_text("IS_INSTALLED = False\n", encoding="utf-8")

    # Change working directory to tmp_path where the folder exists
    monkeypatch.chdir(tmp_path)

    app = Flask("test_app")
    app.config["FLEXMEASURES_PLUGINS"] = [pkg_name]

    register_plugins(app)

    # Verify that the loaded plugin is the installed module and its Blueprint was registered
    assert pkg_name in app.config["LOADED_PLUGINS"]
    assert "installed_bp" in app.blueprints


def test_explicit_file_path_plugin(tmp_path):
    """Test that an explicit file path loads via spec_from_file_location."""
    plugin_dir = tmp_path / "my_custom_filepath_plugin"
    plugin_dir.mkdir()
    init_file = plugin_dir / "__init__.py"
    init_file.write_text(
        "from flask import Blueprint\n"
        "custom_bp = Blueprint('custom_bp', __name__)\n"
        "__version__ = '2.0.0'\n",
        encoding="utf-8",
    )

    app = Flask("test_app")
    app.config["FLEXMEASURES_PLUGINS"] = [str(plugin_dir)]

    register_plugins(app)

    assert "my_custom_filepath_plugin" in app.config["LOADED_PLUGINS"]
    assert "custom_bp" in app.blueprints


def test_uninstalled_plugin_falls_back_to_relative_path(tmp_path, monkeypatch):
    """Test that when a bare package name is not installed, it falls back to a relative folder in cwd with a warning."""
    pkg_name = "uninstalled_fallback_plugin"
    plugin_dir = tmp_path / pkg_name
    plugin_dir.mkdir()
    init_file = plugin_dir / "__init__.py"
    init_file.write_text(
        "from flask import Blueprint\n"
        "fallback_bp = Blueprint('fallback_bp', __name__)\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.delitem(sys.modules, pkg_name, raising=False)

    app = Flask("test_app")
    app.config["FLEXMEASURES_PLUGINS"] = [pkg_name]

    register_plugins(app)

    assert pkg_name in app.config["LOADED_PLUGINS"]
    assert "fallback_bp" in app.blueprints


def test_nonexistent_plugin_logs_error():
    """Test that a plugin that neither exists as a package nor as a file path logs an error."""
    app = Flask("test_app")
    app.config["FLEXMEASURES_PLUGINS"] = ["nonexistent_package_xyz_123"]

    register_plugins(app)

    assert "nonexistent_package_xyz_123" not in app.config["LOADED_PLUGINS"]
