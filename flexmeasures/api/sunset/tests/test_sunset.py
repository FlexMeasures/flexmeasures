import pytest

from flask import url_for


@pytest.mark.parametrize(
    "blueprint, api_version_being_sunset",
    [
        ("flexmeasures_api_v1", "1.0"),
        ("flexmeasures_api_v1_1", "1.1"),
        ("flexmeasures_api_v1_2", "1.2"),
        ("flexmeasures_api_v1_3", "1.3"),
        ("flexmeasures_api_v2_0", "2.0"),
    ],
)
def test_sunset(client, blueprint, api_version_being_sunset):
    gone = client.get(url_for(f"{blueprint}.implementation_gone"))
    assert gone.status_code == 410
    assert (
        f"API version {api_version_being_sunset} has been sunset"
        in gone.json["message"]
    )


def test_sunset_uses_api_version_deprecation_config(app, client):
    original_config = app.config["FLEXMEASURES_DEPRECATION_AND_SUNSET"]
    app.config["FLEXMEASURES_DEPRECATION_AND_SUNSET"] = {
        "api-v2_0": {
            "deprecation-date": "2026-08-01",
            "deprecation-link": "https://example.com/api/v2-deprecation",
            "sunset-date": "2026-11-01",
            "sunset-link": "https://example.com/api/v2-sunset",
        },
    }
    try:
        gone = client.get(url_for("flexmeasures_api_v2_0.implementation_gone"))
    finally:
        app.config["FLEXMEASURES_DEPRECATION_AND_SUNSET"] = original_config

    assert gone.status_code == 410
    assert "https://example.com/api/v2-sunset" in gone.json["message"]
    assert gone.headers["Deprecation"] == "Fri, 31 Jul 2026 23:59:59 GMT"
    assert gone.headers["Sunset"] == "Sat, 31 Oct 2026 23:59:59 GMT"
    links = gone.headers.getlist("Link")
    assert (
        '<https://example.com/api/v2-deprecation>; rel="deprecation"; type="text/html"'
        in links
    )
    assert (
        '<https://example.com/api/v2-sunset>; rel="sunset"; type="text/html"' in links
    )
