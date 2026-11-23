"""Every response carries the headers that keep browsers from sniffing content types, framing pages and leaking URLs."""

import pytest

EXPECTED_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Content-Security-Policy": "frame-ancestors 'self'",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


@pytest.mark.parametrize(
    "path",
    [
        "/login",  # a UI page
        "/api/v3_0/assets",  # an API response (401 without credentials)
        "/api/v3_0/no-such-endpoint",  # an error response
    ],
)
def test_responses_carry_security_headers(client, path):
    response = client.get(path)
    for name, value in EXPECTED_HEADERS.items():
        assert response.headers.get(name) == value, (name, response.status_code)


def test_security_headers_can_be_left_out(client, app, monkeypatch):
    """Hosts whose reverse proxy sets a header already can switch it off."""
    monkeypatch.setitem(
        app.config,
        "FLEXMEASURES_SECURITY_HEADERS",
        {**EXPECTED_HEADERS, "X-Frame-Options": None},
    )
    response = client.get("/login")
    assert "X-Frame-Options" not in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"
