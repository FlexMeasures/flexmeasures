import logging

import pytest
from flask import Flask

from flexmeasures.utils.plugin_utils import check_config_settings


@pytest.fixture
def bare_app():
    """A minimal app to check plugin settings against, which is not in testing mode.

    Settings are only read from the environment outside of testing mode,
    just like FlexMeasures' own settings are.
    """
    app = Flask("test_plugin_utils")
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
    app = Flask("test_plugin_utils")
    app.testing = True
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


def test_default_does_not_override_a_set_value(bare_app, monkeypatch, caplog):
    """A setting that is set is not touched, and is not reported as missing."""
    monkeypatch.setenv("MY_PLUGIN_COUNTRY", "BE")
    with caplog.at_level(logging.WARNING):
        check_config_settings(bare_app, {"MY_PLUGIN_COUNTRY": {"default": "NL"}})
    assert bare_app.config["MY_PLUGIN_COUNTRY"] == "BE"
    assert caplog.text == ""
