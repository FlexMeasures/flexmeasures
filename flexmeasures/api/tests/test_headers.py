from flask import url_for

from flexmeasures import __version__ as flexmeasures_version


def test_flexmeasures_version_header_on_api_response(client):
    """All API responses should include the FlexMeasures-Version header."""
    response = client.get(url_for("flexmeasures_api_ops.get_ping"))
    assert response.status_code == 200
    assert response.headers.get("FlexMeasures-Version") == flexmeasures_version


def test_flexmeasures_version_header_on_v3_0_response(client):
    """v3_0 API responses should include the FlexMeasures-Version header."""
    response = client.get(url_for("HealthAPI:is_ready"))
    assert response.status_code == 200
    assert response.headers.get("FlexMeasures-Version") == flexmeasures_version


def test_api_version_header_on_v3_0_response(client):
    """All API responses under v3_0 should include the API-Version header."""
    response = client.get(url_for("HealthAPI:is_ready"))
    assert response.status_code == 200
    assert response.headers.get("API-Version") == "v3_0"


def test_no_api_version_header_on_non_v3_0_response(client):
    """Non-v3_0 API responses should not include the API-Version header."""
    response = client.get(url_for("flexmeasures_api_ops.get_ping"))
    assert response.status_code == 200
    assert "API-Version" not in response.headers
