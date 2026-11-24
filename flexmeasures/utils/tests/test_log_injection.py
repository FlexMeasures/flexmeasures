"""Clients cannot write fake log lines through the request path or error messages."""

import logging

import pytest
from flask import Flask, abort

from flexmeasures.utils.error_utils import add_basic_error_handlers, escape_for_log

FAKE_LINE = "[FLEXMEASURES][2026-01-01 00:00:00,000] INFO: user admin logged in"


@pytest.fixture
def bare_app():
    app = Flask(__name__)
    add_basic_error_handlers(app)

    @app.route("/api/v3_0/echo/<text>")
    def echo(text):
        abort(400, description=f"Cannot use '{text}'.")

    return app


def logged_lines(caplog) -> list[str]:
    return [
        line for record in caplog.records for line in record.getMessage().splitlines()
    ]


@pytest.mark.parametrize("separator", ["%0A", "%0D", "%0D%0A", "%E2%80%A8"])
def test_request_path_cannot_add_a_log_line(bare_app, caplog, separator):
    caplog.set_level(logging.INFO)
    response = bare_app.test_client().get(f"/no-such-page{separator}{FAKE_LINE}")
    assert response.status_code == 404
    assert caplog.records, "the 404 should be logged"
    assert not any(line.startswith("[FLEXMEASURES]") for line in logged_lines(caplog))
    assert len(logged_lines(caplog)) == len(caplog.records)


def test_error_message_cannot_add_a_log_line(bare_app, caplog):
    caplog.set_level(logging.INFO)
    response = bare_app.test_client().get(f"/api/v3_0/echo/x%0A{FAKE_LINE}")
    assert response.status_code == 400
    assert caplog.records
    assert not any(line.startswith("[FLEXMEASURES]") for line in logged_lines(caplog))


def test_escape_for_log():
    assert escape_for_log("a\nb\r\tc\x00 é") == "a\\nb\\r\\tc\\x00\\u2028é"
