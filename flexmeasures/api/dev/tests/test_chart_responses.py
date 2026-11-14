"""Chart endpoints answer with JSON typed as JSON."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from flexmeasures.data.models.time_series import Sensor

WINDOW = {"start": "2021-05-02T00:00:00+02:00", "end": "2021-05-03T00:00:00+02:00"}
MARKUP_NAME = "gas <img src=x onerror=alert(1)>"


@pytest.fixture
def sensor_with_markup_in_its_name(db):
    """The gas sensor, temporarily renamed to a name holding markup."""
    sensor = db.session.execute(
        select(Sensor).filter_by(name="some gas sensor")
    ).scalar_one()
    sensor.name = MARKUP_NAME
    db.session.commit()
    yield sensor
    sensor.name = "some gas sensor"
    db.session.commit()


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
@pytest.mark.parametrize(
    "path",
    [
        "/api/dev/sensor/{sensor_id}/chart",
        "/api/dev/sensor/{sensor_id}/chart_data",
        "/api/dev/sensor/{sensor_id}/chart_annotations",
        "/api/v3_0/assets/{asset_id}/chart",
        "/api/v3_0/assets/{asset_id}/chart_data",
        "/api/v3_0/assets/{asset_id}/chart_annotations",
    ],
)
def test_chart_endpoints_answer_as_json(
    client, setup_api_test_data, requesting_user, sensor_with_markup_in_its_name, path
):
    """A browser opening a chart URL directly must not render the JSON as HTML, where a name holding markup would run."""
    sensor = sensor_with_markup_in_its_name
    url = path.format(sensor_id=sensor.id, asset_id=sensor.generic_asset_id)
    response = client.get(url, query_string=WINDOW)
    assert response.status_code == 200, response.data
    assert response.mimetype == "application/json"
    response.get_json()  # the body is valid JSON
    if path.endswith("/chart") and path.startswith("/api/dev"):
        # This is the case the type matters for: json.dumps leaves the markup in the name as it is.
        assert "<img src=x onerror=alert(1)>" in response.data.decode()
