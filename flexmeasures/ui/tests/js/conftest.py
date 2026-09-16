"""Fixtures for running the UI's JavaScript modules in a real browser.

The modules under `flexmeasures/ui/static/js` are plain ES modules,
so they can be exercised without a running FlexMeasures instance.
A small HTTP server serves them, because ES module imports do not work over `file://`,
and a headless browser runs the assertions.

No Node.js toolchain is involved: the assertions are plain JavaScript in a served page,
and pytest reports the results.
"""

from __future__ import annotations

import http.server
import itertools
import json
import socket
import socketserver
import threading
from pathlib import Path

import pytest

STATIC_JS = Path(__file__).resolve().parents[3] / "ui" / "static" / "js"

# Layered so that whichever budget a slow machine exhausts, the page has already said why:
# the page's own watchdog fires first, then the wait for it, then the HTTP client.
PAGE_BUDGET_MS = 20_000
WAIT_BUDGET_S = 60
CLIENT_TIMEOUT_S = 120

PAGE_TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<title>running</title>
<pre id="results"></pre>
<script>
// Collected here rather than in the module below,
// because an import that fails takes the whole module with it,
// and we still want to report that as a failed check rather than as a hang.
window.__results = [];
window.check = (label, passed, detail) => window.__results.push({{label, passed, detail: detail || ""}});
window.eq = (label, actual, expected) => window.check(
    label,
    JSON.stringify(actual) === JSON.stringify(expected),
    `actual ${{JSON.stringify(actual)}}, expected ${{JSON.stringify(expected)}}`
);
window.__finish = () => {{
    document.getElementById("results").textContent = JSON.stringify(window.__results);
    document.title = "done";
}};
window.addEventListener("error", (event) => {{
    window.check("the test module loaded and ran", false, String(event.message || event.error));
    window.__finish();
}});
window.addEventListener("unhandledrejection", (event) => {{
    window.check("the test module settled its promises", false, String(event.reason));
    window.__finish();
}});
setTimeout(() => {{
    if (document.title !== "done") {{
        window.check(`the test module finished within ${{{page_budget_ms} / 1000}}s`, false, "timed out");
        window.__finish();
    }}
}}, {page_budget_ms});
</script>
<script type="module">
{body}
window.__finish();
</script>
"""


class _Handler(http.server.SimpleHTTPRequestHandler):
    # Each run registers its page under its own token and asks for that URL,
    # so a request cannot be served the page of a neighbouring run, and nothing can be answered from cache.
    pages: dict[str, str] = {}

    def _send(self, body: bytes, content_type: str):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/run/"):
            body = type(self).pages.get(self.path[len("/run/") :])
            if body is None:
                self.send_error(404)
                return
            self._send(
                PAGE_TEMPLATE.format(body=body, page_budget_ms=PAGE_BUDGET_MS).encode(),
                "text/html",
            )
            return
        if self.path.startswith("/js/"):
            target = STATIC_JS / self.path[len("/js/") :].split("?")[0]
            if target.is_file() and STATIC_JS in target.resolve().parents:
                self._send(target.read_bytes(), "text/javascript")
                return
        self.send_error(404)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="session")
def js_runner():
    """Return a callable that runs a snippet of JavaScript and yields its checks.

    The snippet may import from `/js/<module>.js` and should call `check(...)` or `eq(...)`.
    """
    selenium = pytest.importorskip(
        "selenium",
        reason="install the test dependency group to run the JavaScript tests",
    )
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.common.exceptions import TimeoutException, WebDriverException

    del selenium

    options = Options()
    for flag in (
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--window-size=1200,800",
        # A small /dev/shm is the usual reason headless Chrome stalls on a busy machine.
        "--disable-dev-shm-usage",
        # Headless Chrome throttles timers and rendering in windows it thinks are hidden,
        # which is every window here,
        # and which is what makes the page's own watchdog unreliable.
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-extensions",
        "--no-first-run",
    ):
        options.add_argument(flag)
    # Selenium reads its HTTP client timeout from the global socket default at construction (see `ClientConfig`),
    # so without this it inherits whatever any other library happened to leave there,
    # and a busy machine fails with a connection error instead of a report.
    # The budgets are layered on purpose: the page gives up first and reports (PAGE_BUDGET_MS),
    # then the wait for it, and only then the client.
    previous_default_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(CLIENT_TIMEOUT_S)
    try:
        driver = webdriver.Chrome(options=options)
    except WebDriverException as error:  # pragma: no cover
        pytest.skip(f"no usable Chrome for the JavaScript tests: {error}")
    finally:
        socket.setdefaulttimeout(previous_default_timeout)

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/run/"

    run_counter = itertools.count()

    def run(
        body: str, timezone: str | None = None, wait_s: float = WAIT_BUDGET_S
    ) -> list[dict]:
        """Run a snippet, optionally pretending the browser sits in a given timezone.

        Overriding the timezone keeps tests that depend on one independent of the machine running them,
        such as those covering daylight saving transitions.
        """
        token = str(next(run_counter))
        _Handler.pages[token] = body
        # Registering the page and giving it back are one unit:
        # anything between them can raise, and a page left registered would stay there for the session.
        try:
            # "" restores the host timezone,
            # so one test cannot leak its override into the next.
            driver.execute_cdp_cmd(
                "Emulation.setTimezoneOverride", {"timezoneId": timezone or ""}
            )
            driver.get(url + token)
            try:
                WebDriverWait(driver, wait_s).until(lambda d: d.title == "done")
            except TimeoutException:
                # Ask the page for what it has collected, rather than reading the element it
                # writes on finishing: a page that timed out is precisely one that never did.
                checks = driver.execute_script("return window.__results || [];")
                return list(checks) + [
                    {
                        "label": f"the page finished within {wait_s}s",
                        "passed": False,
                        "detail": f"{len(checks)} check(s) had been reported when the wait ran out",
                    }
                ]
            return json.loads(driver.find_element("id", "results").text)
        finally:
            _Handler.pages.pop(token, None)

    try:
        yield run
    finally:
        driver.quit()
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="session")
def js_budgets() -> dict[str, float]:
    """The budgets the harness runs to.

    Handed out for the same reason as `js_pages`, though only for consistency here:
    these are literals, so a second module identity would hold equal values rather than different ones.
    """
    return {
        "page_ms": PAGE_BUDGET_MS,
        "wait_s": WAIT_BUDGET_S,
        "client_s": CLIENT_TIMEOUT_S,
    }


@pytest.fixture(scope="session")
def js_pages() -> dict[str, str]:
    """The pages the harness currently has registered.

    Handed out rather than imported, because pytest gives a conftest its own module identity:
    importing this module again yields a second `_Handler`, with a registry nothing writes to.
    """
    return _Handler.pages


@pytest.fixture
def assert_js(js_runner):
    """Run JavaScript checks and fail with every check that did not pass."""

    def _assert(body: str, timezone: str | None = None):
        checks = js_runner(body, timezone)
        assert checks, "the JavaScript module produced no checks"
        failures = [c for c in checks if not c["passed"]]
        assert not failures, "\n".join(f"{c['label']}: {c['detail']}" for c in failures)
        return checks

    return _assert
