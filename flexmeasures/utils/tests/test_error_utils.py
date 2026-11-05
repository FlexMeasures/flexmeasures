import pytest
from flask import Flask

from flexmeasures.utils.error_utils import add_basic_error_handlers


@pytest.fixture
def bare_app():
    """A Flask app with only the generic error handler, and one HTML fallback to tell the two apart."""
    app = Flask(__name__)
    add_basic_error_handlers(app)
    app.NotFound_handler_html = lambda error: (
        "<html>not found</html>",
        404,
        {"Content-Type": "text/html"},
    )

    @app.route("/api/v3_0/exists")
    def api_route():
        return {"ok": True}

    return app


@pytest.mark.parametrize(
    "path",
    ["/api/v3_0/no-such-endpoint", "/api/no-such-version/sensors", "/api"],
)
def test_unknown_api_url_gets_json_404(bare_app, path):
    """An unmatched URL under /api is answered in JSON, also without a JSON content type (as with curl)."""
    response = bare_app.test_client().get(path)
    assert response.status_code == 404
    assert response.is_json
    assert response.json["status"] == 404
    assert "message" in response.json


def test_wrong_method_on_api_route_gets_json_405(bare_app):
    """A method an API route does not take matches no route either, and is answered in JSON, too."""
    response = bare_app.test_client().post("/api/v3_0/exists")
    assert response.status_code == 405
    assert response.is_json
    assert response.json["status"] == 405
    assert "message" in response.json


def test_url_merely_starting_with_api_still_gets_html_404(bare_app):
    """A path such as /apiary is not under /api, so a plain request gets the HTML error page."""
    response = bare_app.test_client().get("/apiary")
    assert response.status_code == 404
    assert not response.is_json
    assert response.get_data(as_text=True) == "<html>not found</html>"


def test_unknown_non_api_url_still_gets_html_404(bare_app):
    """Outside /api, the HTML error page is still used for a plain (non-JSON) request."""
    response = bare_app.test_client().get("/no-such-page")
    assert response.status_code == 404
    assert not response.is_json
    assert response.content_type.startswith("text/html")
    assert response.get_data(as_text=True) == "<html>not found</html>"


def test_unknown_non_api_url_gets_json_404_for_json_request(bare_app):
    """A JSON request keeps getting a JSON error, wherever it is made."""
    response = bare_app.test_client().get(
        "/no-such-page", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 404
    assert response.is_json
