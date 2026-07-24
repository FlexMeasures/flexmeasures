import pytest
from flask import Flask

from flexmeasures.utils.config_utils import parse_bool_env, read_env_vars


@pytest.mark.parametrize(
    "value, expected",
    [
        ("True", True),
        ("true", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        (" true ", True),
        ("False", False),
        ("false", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("", False),
        ("  ", False),
    ],
)
def test_parse_bool_env(value, expected):
    assert parse_bool_env(value) is expected


@pytest.mark.parametrize(
    "env_value, expected",
    [("True", True), ("False", False), ("1", True), ("0", False)],
)
def test_read_env_vars_parses_booleans(monkeypatch, env_value, expected):
    monkeypatch.setenv("SECURITY_TWO_FACTOR", env_value)
    app = Flask(__name__)
    app.config["SECURITY_TWO_FACTOR"] = False
    read_env_vars(app)
    assert app.config["SECURITY_TWO_FACTOR"] is expected


def test_read_env_vars_sentry_sdn_fallback(monkeypatch):
    monkeypatch.setenv("SENTRY_SDN", "https://legacy@sentry.example/1")
    app = Flask(__name__)
    app.config["SENTRY_DSN"] = None
    read_env_vars(app)
    assert app.config["SENTRY_DSN"] == "https://legacy@sentry.example/1"

    # SENTRY_DSN takes precedence over the legacy typo
    monkeypatch.setenv("SENTRY_DSN", "https://proper@sentry.example/2")
    read_env_vars(app)
    assert app.config["SENTRY_DSN"] == "https://proper@sentry.example/2"
