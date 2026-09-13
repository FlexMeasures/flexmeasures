import pytest

import pandas as pd
from flask import url_for

from flexmeasures.api.sunset import SUNSET_INFO
from flexmeasures.utils.time_utils import to_http_time


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
        "api-v2.0": {
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


@pytest.mark.parametrize(
    "blueprint",
    [
        "flexmeasures_api_v1",
        "flexmeasures_api_v1_3",
        "flexmeasures_api_v2_0",
    ],
)
def test_sunset_falls_back_to_built_in_info(app, client, blueprint):
    """Without a host override, sunset endpoints report the details from SUNSET_INFO."""
    info = {i["blueprint"].name: i for i in SUNSET_INFO}[blueprint]

    original_config = app.config["FLEXMEASURES_DEPRECATION_AND_SUNSET"]
    app.config["FLEXMEASURES_DEPRECATION_AND_SUNSET"] = {}
    try:
        gone = client.get(url_for(f"{blueprint}.implementation_gone"))
    finally:
        app.config["FLEXMEASURES_DEPRECATION_AND_SUNSET"] = original_config

    assert gone.status_code == 410
    assert info["sunset_link"] in gone.json["message"]
    assert gone.headers["Deprecation"] == to_http_time(
        pd.Timestamp(info["deprecation_date"]) - pd.Timedelta("1s")
    )
    assert gone.headers["Sunset"] == to_http_time(
        pd.Timestamp(info["sunset_date"]) - pd.Timedelta("1s")
    )
    links = gone.headers.getlist("Link")
    assert (
        f"<{info['deprecation_link']}>; rel=\"deprecation\"; type=\"text/html\""
        in links
    )
    assert f"<{info['sunset_link']}>; rel=\"sunset\"; type=\"text/html\"" in links
