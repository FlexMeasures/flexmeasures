import logging

import pytest
import sentry_sdk
from flask import Flask
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.transport import Transport
from werkzeug.exceptions import InternalServerError, NotFound, SecurityError

from flexmeasures.data import _is_running_db_upgrade_command
from flexmeasures.utils.app_utils import (
    _make_sentry_daily_rate_limiter,
    _sentry_filter_notfound,
    init_sentry,
    provision_default_template_assets_on_startup,
)
from flexmeasures.utils.error_utils import add_basic_error_handlers


class RecordingTransport(Transport):
    """Sentry transport that records events instead of sending them."""

    def __init__(self, options=None):
        super().__init__(options)
        self.events = []

    def capture_envelope(self, envelope):
        event = envelope.get_event()
        if event is not None:
            self.events.append(event)


def make_hint(exc):
    """Helper to build a Sentry hint dict from an exception."""
    try:
        raise exc
    except type(exc):
        import sys

        return {"exc_info": sys.exc_info()}


def test_sentry_filter_drops_notfound():
    """404 NotFound errors should be filtered out before reaching Sentry."""
    event = {"message": "Not Found"}
    hint = make_hint(NotFound())
    assert _sentry_filter_notfound(event, hint) is None


def test_sentry_filter_passes_other_errors():
    """Non-404 errors should be passed through unchanged."""
    event = {"message": "Internal Server Error"}
    hint = make_hint(InternalServerError())
    assert _sentry_filter_notfound(event, hint) is event


def test_sentry_filter_drops_untrusted_host_security_error():
    """Untrusted-host SecurityErrors with exc_info should still be reported."""
    event = {"message": "Security Error"}
    hint = make_hint(
        SecurityError(
            "Host 'static.152.131.199.138.clients.your-server.de' is not trusted."
        )
    )
    assert _sentry_filter_notfound(event, hint) is event


def test_sentry_filter_passes_events_without_exc_info():
    """Events without exc_info (e.g. captured messages) should be passed through."""
    event = {"message": "some log message"}
    hint = {}
    assert _sentry_filter_notfound(event, hint) is event


def test_sentry_filter_drops_flexmeasures_notfound_log_record():
    """FlexMeasures logs handled 404s without exc_info."""
    event = {"message": "Not Found"}
    log_record = app_logger_record('NotFound - URL was: /missing - "Not Found"')
    hint = {"log_record": log_record}
    assert _sentry_filter_notfound(event, hint) is None


def test_sentry_filter_passes_other_log_records():
    """Other logging events should be passed through unchanged."""
    event = {"message": "some log message"}
    log_record = app_logger_record("NotFound in unrelated background task")
    hint = {"log_record": log_record}
    assert _sentry_filter_notfound(event, hint) is event


def test_sentry_filter_drops_untrusted_host_security_error_log_record():
    """Handled untrusted-host SecurityErrors are logged without exc_info."""
    event = {"message": "Security Error"}
    log_record = app_logger_record(
        "SecurityError - URL was: /admin/config.php - \"Host '0.0.0.0' is not trusted.\""
    )
    hint = {"log_record": log_record}
    assert _sentry_filter_notfound(event, hint) is None


def test_sentry_filter_drops_flask_404_logging_event():
    """The Flask error handler logs 404s with a LogRecord hint."""
    app = Flask(__name__)
    add_basic_error_handlers(app)
    transport = RecordingTransport()
    hints_seen = []
    previous_client = sentry_sdk.get_client()

    def before_send(event, hint):
        hints_seen.append(hint)
        return _sentry_filter_notfound(event, hint)

    sentry_sdk.init(
        dsn="https://public@example.com/1",
        integrations=[FlaskIntegration()],
        before_send=before_send,
        transport=transport,
    )
    try:
        response = app.test_client().get("/api/missing")
    finally:
        sentry_sdk.flush()
        sentry_sdk.get_client().close()
        sentry_sdk.get_global_scope().set_client(previous_client)

    assert response.status_code == 404
    assert transport.events == []
    assert any("log_record" in hint for hint in hints_seen)


def test_sentry_daily_rate_limiter_drops_events_after_limit(app, clean_redis):
    rate_limit = _make_sentry_daily_rate_limiter(app, daily_rate_limit=2)
    events = [{"message": f"error {i}"} for i in range(3)]

    assert rate_limit(events[0], {}) is events[0]
    assert rate_limit(events[1], {}) is events[1]
    assert rate_limit(events[2], {}) is None
    counter_key = next(
        key for key in app.redis_connection.scan_iter("flexmeasures:sentry-events:*")
    )
    assert app.redis_connection.get(counter_key) == b"3"
    assert 0 < app.redis_connection.ttl(counter_key) <= 24 * 60 * 60


def test_sentry_daily_rate_limiter_fails_open_without_redis(app, monkeypatch, caplog):
    rate_limit = _make_sentry_daily_rate_limiter(app, daily_rate_limit=1)
    event = {"message": "error"}

    def fail_pipeline():
        from redis.exceptions import ConnectionError

        raise ConnectionError("Connection refused")

    monkeypatch.setattr(app.redis_connection, "pipeline", fail_pipeline)
    with caplog.at_level(logging.WARNING):
        assert rate_limit(event, {}) is event
        assert rate_limit(event, {}) is event

    assert caplog.text.count("Sentry daily rate limit") == 1


@pytest.mark.parametrize("invalid_limit", [0, -1, 1.5, "10", True])
def test_init_sentry_warns_and_ignores_invalid_daily_rate_limit(
    app, monkeypatch, caplog, invalid_limit
):
    sentry_options = {}
    monkeypatch.setitem(app.config, "SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.setitem(
        app.config, "FLEXMEASURES_SENTRY_DAILY_RATE_LIMIT", invalid_limit
    )
    monkeypatch.setattr(
        sentry_sdk, "init", lambda **kwargs: sentry_options.update(kwargs)
    )

    with caplog.at_level(logging.WARNING):
        init_sentry(app)
        sentry_options["before_send"]({"message": "error"}, {})

    assert caplog.text.count("must be a positive integer or None") == 1


def test_init_sentry_filters_notfound_before_counting_towards_limit(
    app, clean_redis, monkeypatch
):
    sentry_options = {}
    monkeypatch.setitem(app.config, "SENTRY_DSN", "https://public@example.com/1")
    monkeypatch.setitem(app.config, "FLEXMEASURES_SENTRY_DAILY_RATE_LIMIT", 1)
    monkeypatch.setattr(
        sentry_sdk, "init", lambda **kwargs: sentry_options.update(kwargs)
    )
    init_sentry(app)
    before_send = sentry_options["before_send"]
    notfound_event = {"message": "Not Found"}
    error_event = {"message": "Internal Server Error"}

    assert before_send(notfound_event, make_hint(NotFound())) is None
    assert before_send(error_event, make_hint(InternalServerError())) is error_event
    assert before_send(error_event, make_hint(InternalServerError())) is None


def app_logger_record(message):
    return logging.LogRecord(
        "flexmeasures",
        logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_provision_default_template_assets_on_startup_skips_old_schema(
    app, monkeypatch, caplog
):
    def fail_if_called(db):
        raise AssertionError("Template provisioning should not run.")

    monkeypatch.setattr(app, "testing", False)
    monkeypatch.setitem(app.config, "FLEXMEASURES_ENV", "production")
    monkeypatch.setitem(
        app.config, "FLEXMEASURES_CREATE_TEMPLATE_ASSETS_ON_STARTUP", True
    )
    monkeypatch.setattr(app, "database_schema_is_migrated_to_head", False)
    monkeypatch.setattr(
        "flexmeasures.data.scripts.data_gen.provision_default_template_assets",
        fail_if_called,
    )

    with caplog.at_level(logging.INFO):
        provision_default_template_assets_on_startup(app)

    assert "Skipping startup template provisioning" in caplog.text


def test_is_running_db_upgrade_command(monkeypatch):
    monkeypatch.setattr("sys.argv", ["/path/to/flexmeasures", "db", "upgrade", "--sql"])

    assert _is_running_db_upgrade_command() is True


def test_is_running_db_upgrade_command_false_for_other_db_commands(monkeypatch):
    monkeypatch.setattr("sys.argv", ["/path/to/flexmeasures", "db", "current"])

    assert _is_running_db_upgrade_command() is False
