from __future__ import annotations

import pytest

from flask import url_for

from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures import Sensor
from flexmeasures.api.v3_0.tests.utils import get_sensor_post_data
from flexmeasures.data.schemas.sensors import SensorSchema
from flexmeasures.data.models.generic_assets import GenericAsset

sensor_schema = SensorSchema()


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_fetch_one_sensor(
    client,
    setup_api_test_data: dict[str, Sensor],
    requesting_user,
):
    sensor_id = 1
    response = client.get(
        url_for("SensorAPI:fetch_one", id=sensor_id),
    )
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 200
    assert response.json["name"] == "some gas sensor"
    assert response.json["unit"] == "m³/h"
    assert response.json["timezone"] == "UTC"
    assert response.json["event_resolution"] == "PT10M"
    asset = GenericAsset.query.filter_by(
        id=response.json["generic_asset_id"]
    ).one_or_none()
    assert asset.name == "incineration line"


@pytest.mark.parametrize(
    "requesting_user, status_code",
    [(None, 401), ("test_prosumer_user_2@seita.nl", 403)],
    indirect=["requesting_user"],
)
def test_fetch_one_sensor_no_auth(
    client, setup_api_test_data: dict[str, Sensor], requesting_user, status_code
):
    """Test 1: Sensor with id 1 is not in the test_prosumer_user_2@seita.nl's account.
    The Supplier Account as can be seen in flexmeasures/api/v3_0/tests/conftest.py
    Test 2: There is no authentication int the headers"""
    sensor_id = 1

    response = client.get(url_for("SensorAPI:fetch_one", id=sensor_id))
    assert response.status_code == status_code
    if status_code == 403:
        assert (
            response.json["message"]
            == "You cannot be authorized for this content or functionality."
        )
        assert response.json["status"] == "INVALID_SENDER"
    elif status_code == 401:
        assert (
            response.json["message"]
            == "You could not be properly authenticated for this content or functionality."
        )
        assert response.json["status"] == "UNAUTHORIZED"
    else:
        raise NotImplementedError(f"Test did not expect status code {status_code}")


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_post_a_sensor(client, setup_api_test_data, requesting_user):
    post_data = get_sensor_post_data()
    response = client.post(
        url_for("SensorAPI:post"),
        json=post_data,
    )
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 201
    assert response.json["name"] == "power"
    assert response.json["event_resolution"] == "PT1H"

    sensor: Sensor = Sensor.query.filter_by(name="power").one_or_none()
    assert sensor is not None
    assert sensor.unit == "kWh"
    assert sensor.attributes["capacity_in_mw"] == 0.0074


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_post_sensor_to_asset_from_unrelated_account(
    client, setup_api_test_data, requesting_user
):
    """Tries to add sensor to account the user doesn't have access to"""
    post_data = get_sensor_post_data()
    response = client.post(
        url_for("SensorAPI:post"),
        json=post_data,
    )
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 403
    assert (
        response.json["message"]
        == "You cannot be authorized for this content or functionality."
    )
    assert response.json["status"] == "INVALID_SENDER"


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_patch_sensor(client, setup_api_test_data, requesting_user):
    sensor = Sensor.query.filter(Sensor.name == "some gas sensor").one_or_none()

    response = client.patch(
        url_for("SensorAPI:patch", id=sensor.id),
        json={
            "name": "Changed name",
            "attributes": '{"test_attribute": "test_attribute_value"}',
        },
    )
    assert response.json["name"] == "Changed name"
    new_sensor = Sensor.query.filter(Sensor.name == "Changed name").one_or_none()
    assert new_sensor.name == "Changed name"
    assert Sensor.query.filter(Sensor.name == "some gas sensor").one_or_none() is None
    assert new_sensor.attributes["test_attribute"] == "test_attribute_value"


@pytest.mark.parametrize(
    "attribute, value",
    [
        ("generic_asset_id", 8),
        ("entity_address", "ea1.2025-01.io.flexmeasures:fm1.1"),
        ("id", 7),
    ],
)
@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_patch_sensor_for_excluded_attribute(
    client, setup_api_test_data, attribute, value, requesting_user
):
    """Test to change the generic_asset_id that should not be allowed.
    The generic_asset_id is excluded in the partial_sensor_schema"""
    sensor = Sensor.query.filter(Sensor.name == "some temperature sensor").one_or_none()

    response = client.patch(
        url_for("SensorAPI:patch", id=sensor.id),
        json={
            attribute: value,
        },
    )

    print(response.json)
    assert response.status_code == 422
    assert response.json["status"] == "UNPROCESSABLE_ENTITY"
    assert response.json["message"]["json"][attribute] == ["Unknown field."]


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_patch_sensor_non_admin(client, setup_api_test_data, requesting_user):
    """Try to change the name of a sensor with a non admin account"""

    sensor = Sensor.query.filter(Sensor.name == "some temperature sensor").one_or_none()

    response = client.patch(
        url_for("SensorAPI:patch", id=sensor.id),
        json={
            "name": "try to change the name",
        },
    )

    assert response.status_code == 403
    assert response.json["status"] == "INVALID_SENDER"


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_delete_a_sensor(client, setup_api_test_data, requesting_user):
    existing_sensor_id = setup_api_test_data["some temperature sensor"].id
    sensor_data = TimedBelief.query.filter(
        TimedBelief.sensor_id == existing_sensor_id
    ).all()
    sensor_count = len(Sensor.query.all())

    assert isinstance(sensor_data[0].event_value, float)

    delete_sensor_response = client.delete(
        url_for("SensorAPI:delete", id=existing_sensor_id),
    )
    assert delete_sensor_response.status_code == 204
    deleted_sensor = Sensor.query.filter_by(id=existing_sensor_id).one_or_none()
    assert deleted_sensor is None
    assert (
        TimedBelief.query.filter(TimedBelief.sensor_id == existing_sensor_id).all()
        == []
    )
    assert len(Sensor.query.all()) == sensor_count - 1
