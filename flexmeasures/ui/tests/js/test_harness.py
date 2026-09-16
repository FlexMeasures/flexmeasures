"""Checks on the harness that runs the other JavaScript tests."""

from __future__ import annotations

import socket

import pytest

from selenium.webdriver.remote.client_config import ClientConfig

from flexmeasures.ui.tests.js.conftest import (
    CLIENT_TIMEOUT_S,
    PAGE_BUDGET_MS,
    WAIT_BUDGET_S,
)


def test_the_client_outlasts_the_page_and_the_wait_for_it():
    """Whichever budget a slow machine exhausts, the page has already reported why.

    The page's own watchdog has to fire before the wait for it gives up, and both before the HTTP client does,
    or a busy machine produces a connection error naming nothing,
    instead of a failed check naming what did not finish.
    """
    assert PAGE_BUDGET_MS / 1000 < WAIT_BUDGET_S < CLIENT_TIMEOUT_S


def test_the_client_timeout_does_not_depend_on_the_global_socket_default():
    """Selenium reads its client timeout from the global socket default when it is built.

    Any library that sets that global would otherwise decide how long our browser commands may take,
    which is how a busy machine came to fail with a read timeout.
    """
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(0.5)
    try:
        inherited = ClientConfig(remote_server_addr="http://localhost:0").timeout
        assert inherited == 0.5, "selenium no longer reads the global socket default"

        socket.setdefaulttimeout(CLIENT_TIMEOUT_S)
        assert (
            ClientConfig(remote_server_addr="http://localhost:0").timeout
            == CLIENT_TIMEOUT_S
        )
    finally:
        socket.setdefaulttimeout(previous)


def test_each_run_is_served_its_own_page(js_runner):
    """Two runs in a row report their own checks, not one another's."""
    first = js_runner('check("first", true, "");')
    second = js_runner('check("second", true, "");')

    assert [c["label"] for c in first] == ["first"]
    assert [c["label"] for c in second] == ["second"]


def test_a_snippet_that_throws_is_reported_rather_than_hanging(js_runner):
    """An error while the module loads comes back as a failed check."""
    checks = js_runner('throw new Error("module blew up");')

    assert checks, "a throwing snippet reported nothing at all"
    assert any(not c["passed"] and "blew up" in c["detail"] for c in checks), checks


def test_a_run_that_fails_before_loading_leaves_no_page_behind(
    js_runner, js_pages, monkeypatch
):
    """Registering a page and giving it back are one unit.

    Anything between them can raise, and a page left registered would stay there for the session.
    """
    from selenium.webdriver.chrome.webdriver import WebDriver

    registered_before = set(js_pages)

    def refuse(self, url):
        raise RuntimeError("the browser went away")

    monkeypatch.setattr(WebDriver, "get", refuse)
    with pytest.raises(RuntimeError, match="the browser went away"):
        js_runner('check("never reached", true, "");')

    assert set(js_pages) == registered_before
