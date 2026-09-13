import logging
import pytest
from flask import Flask
from werkzeug.sansio.utils import host_is_trusted

from flexmeasures.utils.config_defaults import DevelopmentConfig, ProductionConfig

from flexmeasures.utils.config_utils import (
    get_config_warnings,
    normalize_trusted_hosts,
    parse_bool_env,
    read_env_vars,
)


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
    "var",
    [
        "SECURITY_TWO_FACTOR",
        "MAIL_USE_TLS",
        "MAIL_USE_SSL",
        "FLEXMEASURES_JSON_COMPACT",
        "DEBUG",
    ],
)
@pytest.mark.parametrize(
    "env_value, expected",
    [("True", True), ("False", False), ("1", True), ("0", False)],
)
def test_read_env_vars_parses_booleans(monkeypatch, var, env_value, expected):
    monkeypatch.setenv(var, env_value)
    app = Flask(__name__)
    read_env_vars(app)
    assert app.config[var] is expected


def test_read_env_vars_coerces_even_when_config_holds_a_string(monkeypatch):
    """Coercion keys off the default's type, not the current config value's type."""
    monkeypatch.setenv("MAIL_USE_TLS", "False")
    app = Flask(__name__)
    app.config["MAIL_USE_TLS"] = "True"  # e.g. a config file mistakenly set a string
    read_env_vars(app)
    assert app.config["MAIL_USE_TLS"] is False


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


def test_read_env_vars_parses_sentry_daily_rate_limit(monkeypatch):
    monkeypatch.setenv("FLEXMEASURES_SENTRY_DAILY_RATE_LIMIT", "100")
    app = Flask(__name__)

    read_env_vars(app)

    assert app.config["FLEXMEASURES_SENTRY_DAILY_RATE_LIMIT"] == 100


def test_read_env_vars_reads_trusted_hosts(monkeypatch):
    monkeypatch.setenv("TRUSTED_HOSTS", "flexmeasures.example.com")
    app = Flask(__name__)
    read_env_vars(app)
    assert app.config["TRUSTED_HOSTS"] == "flexmeasures.example.com"


@pytest.mark.parametrize(
    "value, expected",
    [
        # A single host, as an environment variable would provide it.
        ("example.com", ["example.com"]),
        # Werkzeug matches a plain string as one host, so commas must be split out.
        ("a.example.com,b.example.com", ["a.example.com", "b.example.com"]),
        (" a.example.com , b.example.com ", ["a.example.com", "b.example.com"]),
        # Empty segments are dropped.
        ("a.example.com,,", ["a.example.com"]),
        # Werkzeug trusts every host on an empty list, so an empty value must read as unset.
        ("", None),
        ("   ", None),
        (",,", None),
        ([], None),
        # Lists are left alone, and so is the unset default.
        (["a.example.com"], ["a.example.com"]),
        (None, None),
    ],
)
def test_normalize_trusted_hosts(value, expected):
    app = Flask(__name__)
    app.config["TRUSTED_HOSTS"] = value
    normalize_trusted_hosts(app)
    assert app.config["TRUSTED_HOSTS"] == expected


def test_config_warnings_flag_unset_trusted_hosts():
    """An unset TRUSTED_HOSTS is reported, since it leaves generated URLs poisonable."""
    app = Flask(__name__)
    app.config["TRUSTED_HOSTS"] = None
    missing_settings, config_warnings = get_config_warnings(app)
    assert "TRUSTED_HOSTS" in missing_settings
    assert any("TRUSTED_HOSTS" in warning for warning in config_warnings)


def test_empty_trusted_hosts_still_warns():
    """An empty value must not pass as configured.

    Werkzeug trusts every host on an empty list, so leaving it empty would disable
    host validation while silencing the warning that says so.
    """
    app = Flask(__name__)
    app.config["TRUSTED_HOSTS"] = ""  # e.g. TRUSTED_HOSTS= in a container env file.
    normalize_trusted_hosts(app)
    missing_settings, _ = get_config_warnings(app)
    assert "TRUSTED_HOSTS" in missing_settings


def test_development_config_trusts_loopback():
    """A dev server is reached over loopback, so it needs no TRUSTED_HOSTS warning."""
    app = Flask(__name__)
    app.config.from_object(DevelopmentConfig)
    missing_settings, _ = get_config_warnings(app)
    assert "TRUSTED_HOSTS" not in missing_settings

    normalize_trusted_hosts(app)
    for host in ("localhost:5000", "127.0.0.1", "[::1]:5000", "app.localhost:5000"):
        assert host_is_trusted(host, app.config["TRUSTED_HOSTS"]), host
    # Other hosts are still rejected, so development resembles production.
    assert not host_is_trusted("evil.example", app.config["TRUSTED_HOSTS"])


def test_production_config_does_not_trust_any_host():
    """Production must not get a default, so the warning fires until a host sets it."""
    app = Flask(__name__)
    app.config.from_object(ProductionConfig)
    assert app.config["TRUSTED_HOSTS"] is None
    missing_settings, _ = get_config_warnings(app)
    assert "TRUSTED_HOSTS" in missing_settings


def test_config_warnings_silent_when_trusted_hosts_is_set():
    app = Flask(__name__)
    app.config["TRUSTED_HOSTS"] = ["flexmeasures.example.com"]
    missing_settings, config_warnings = get_config_warnings(app)
    assert "TRUSTED_HOSTS" not in missing_settings
    assert not any("TRUSTED_HOSTS" in warning for warning in config_warnings)


def test_create_app_in_test_does_not_break_caplog(monkeypatch, caplog):
    """Building a custom app inside a test does not overwrite root logger handlers or break caplog."""
    import flexmeasures.ui
    from flexmeasures.app import create as create_app

    monkeypatch.setattr(flexmeasures.ui, "register_at", lambda app: None)
    custom_app = create_app(env="testing")
    assert custom_app.testing is True

    with caplog.at_level(logging.WARNING):
        logging.getLogger().warning("test warning after create_app")

    assert any(
        record.message == "test warning after create_app" for record in caplog.records
    )


def test_create_app_do_configure_logging_flag(monkeypatch):
    """create_app respects do_configure_logging."""
    import flexmeasures.ui
    from flexmeasures.app import create as create_app

    monkeypatch.setattr(flexmeasures.ui, "register_at", lambda app: None)
    called = []
    monkeypatch.setattr(
        "flexmeasures.utils.config_utils.configure_logging",
        lambda: called.append(True),
    )
    create_app(env="testing", do_configure_logging=False)
    assert not called
