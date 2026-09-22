"""The endpoints supporting the FlexMeasures UI, which its charts call."""

import pytest
from sqlalchemy import select

from flexmeasures.data.models.time_series import Sensor


def _gas_sensor(db) -> Sensor:
    return db.session.execute(
        select(Sensor).filter_by(name="some gas sensor")
    ).scalar_one()


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
@pytest.mark.parametrize(
    "prefix",
    [
        "/api/ui",
        # Their former prefix, which keeps working until FlexMeasures v2.
        "/api/dev",
    ],
)
@pytest.mark.parametrize("endpoint", ["chart", "chart_data", "chart_annotations"])
def test_sensor_chart_endpoints(
    client, setup_api_test_data, requesting_user, db, prefix, endpoint
):
    """A sensor's chart, its data and its annotations can be fetched under the UI-support prefix, and under the former one."""
    sensor = _gas_sensor(db)
    response = client.get(
        f"{prefix}/sensor/{sensor.id}/{endpoint}",
        query_string={
            "start": "2021-05-02T00:00:00+02:00",
            "end": "2021-05-03T00:00:00+02:00",
        },
    )
    assert response.status_code == 200, response.data


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_chart_attributes(client, setup_api_test_data, requesting_user, db):
    """The graphs page reads a sensor's and an asset's name, timezone and time range from these endpoints."""
    sensor = _gas_sensor(db)

    response = client.get(f"/api/ui/sensor/{sensor.id}")
    assert response.status_code == 200, response.data
    assert set(response.json) == {"name", "timezone", "timerange"}
    assert response.json["name"] == "some gas sensor"

    response = client.get(f"/api/ui/asset/{sensor.generic_asset_id}")
    assert response.status_code == 200, response.data
    assert set(response.json) == {"name", "timezone", "timerange_of_sensors_to_show"}
    assert response.json["name"] == "incineration line"


def test_chart_endpoints_need_a_logged_in_user(client, setup_api_test_data, db):
    sensor = _gas_sensor(db)
    assert client.get(f"/api/ui/sensor/{sensor.id}/chart_data").status_code == 401
