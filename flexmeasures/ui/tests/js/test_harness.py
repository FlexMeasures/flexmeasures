"""Checks on the harness that runs the other JavaScript tests."""

from __future__ import annotations

import socket

import pytest

pytest.importorskip(
    "selenium",
    reason="install the test dependency group to run the JavaScript tests",
)

from selenium.webdriver.remote.client_config import ClientConfig  # noqa: E402


def test_the_client_outlasts_the_page_and_the_wait_for_it(js_budgets):
    """Whichever budget a slow machine exhausts, the page has already reported why.

    The page's own watchdog has to fire before the wait for it gives up, and both before the HTTP client does,
    or a busy machine produces a connection error naming nothing,
    instead of a failed check naming what did not finish.
    """
    assert js_budgets["page_ms"] / 1000 < js_budgets["wait_s"] < js_budgets["client_s"]


def test_the_global_socket_default_is_what_decides_the_client_timeout(js_budgets):
    """Selenium reads its client timeout from the global socket default when it is built.

    That is why the harness pins the global rather than leaving it:
    any library that sets it would otherwise decide how long our browser commands may take,
    which is how a busy machine came to fail with a read timeout.
    """
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(0.5)
    try:
        inherited = ClientConfig(remote_server_addr="http://localhost:0").timeout
        assert inherited == 0.5, "selenium no longer reads the global socket default"

        socket.setdefaulttimeout(js_budgets["client_s"])
        assert (
            ClientConfig(remote_server_addr="http://localhost:0").timeout
            == js_budgets["client_s"]
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


def test_a_page_that_never_finishes_reports_what_it_had(js_runner):
    """A wait that runs out comes back with the checks the page had already reported.

    Reading the element the page writes on finishing would return nothing here,
    a page that timed out being precisely one that never wrote it.
    """
    checks = js_runner(
        'check("got this far", true, "");\n' "await new Promise(() => {});",
        wait_s=2,
    )

    labels = [c["label"] for c in checks]
    assert "got this far" in labels, checks
    assert any(
        not c["passed"] and c["label"].startswith("the page finished within")
        for c in checks
    ), checks
