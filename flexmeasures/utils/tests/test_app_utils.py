import logging

import sentry_sdk
from flask import Flask
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.transport import Transport
from werkzeug.exceptions import InternalServerError, NotFound

from flexmeasures.utils.app_utils import _sentry_filter_notfound
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
