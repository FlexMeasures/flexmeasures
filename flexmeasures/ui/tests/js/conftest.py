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
import json
import socketserver
import threading
from pathlib import Path

import pytest

STATIC_JS = Path(__file__).resolve().parents[3] / "ui" / "static" / "js"

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
        window.check("the test module finished within 20s", false, "timed out");
        window.__finish();
    }}
}}, 20000);
</script>
<script type="module">
{body}
window.__finish();
</script>
"""


class _Handler(http.server.SimpleHTTPRequestHandler):
    page_body = ""

    def _send(self, body: bytes, content_type: str):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/":
            self._send(
                PAGE_TEMPLATE.format(body=type(self).page_body).encode(), "text/html"
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
        "selenium", reason="install the test dependency group to run the JavaScript tests"
    )
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.common.exceptions import WebDriverException

    del selenium

    options = Options()
    for flag in ("--headless=new", "--disable-gpu", "--no-sandbox", "--window-size=1200,800"):
        options.add_argument(flag)
    try:
        driver = webdriver.Chrome(options=options)
    except WebDriverException as error:  # pragma: no cover
        pytest.skip(f"no usable Chrome for the JavaScript tests: {error}")

    server = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"

    def run(body: str, timezone: str | None = None) -> list[dict]:
        """Run a snippet, optionally pretending the browser sits in a given timezone.

        Overriding the timezone keeps tests that depend on one, such as daylight saving
        transitions, independent of the machine running them.
        """
        _Handler.page_body = body
        # "" restores the host timezone, so one test cannot leak its override into the next.
        driver.execute_cdp_cmd(
            "Emulation.setTimezoneOverride", {"timezoneId": timezone or ""}
        )
        driver.get(url)
        WebDriverWait(driver, 30).until(lambda d: d.title == "done")
        return json.loads(driver.find_element("id", "results").text)

    try:
        yield run
    finally:
        driver.quit()
        server.shutdown()
        server.server_close()


@pytest.fixture
def assert_js(js_runner):
    """Run JavaScript checks and fail with every check that did not pass."""

    def _assert(body: str, timezone: str | None = None):
        checks = js_runner(body, timezone)
        assert checks, "the JavaScript module produced no checks"
        failures = [c for c in checks if not c["passed"]]
        assert not failures, "\n".join(
            f"{c['label']}: {c['detail']}" for c in failures
        )
        return checks

    return _assert
