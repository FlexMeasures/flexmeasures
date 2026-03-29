from werkzeug.exceptions import NotFound, InternalServerError

from flexmeasures.utils.app_utils import _sentry_filter_notfound


def make_hint(exc):
    """Helper to build a Sentry hint dict from an exception."""
    try:
        raise exc
    except type(exc):
        import sys

        return {"exc_info": sys.exc_info()}


def test_sentry_filter_drops_notfound():
    """404 NotFound errors should be filtered out (return None) before reaching Sentry."""
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
