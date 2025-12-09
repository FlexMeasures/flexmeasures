from flask import url_for
import pytest
from sqlalchemy import select

from flexmeasures.api.tests.utils import AccountContext
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures.api.v3_0.tests.utils import get_asset_post_data, generate_csv_content


@pytest.mark.parametrize(
    "requesting_user",
    [
        "test_admin_user@seita.nl",  # has the "site-admin" role
        "test_prosumer_user_2@seita.nl",  # has the "account-admin" role
    ],
    indirect=True,
)
def test_post_an_asset_as_admin(client, setup_api_fresh_test_data, requesting_user, db):
    """
    Post one extra asset, as an admin user.
    """
    with AccountContext("Test Prosumer Account") as prosumer:
        post_data = get_asset_post_data(
            account_id=prosumer.id,
            asset_type_id=prosumer.generic_assets[0].generic_asset_type.id,
        )
    if requesting_user.email == "test_prosumer_user_2@seita.nl":
        post_data["name"] = "Test battery 3"
    post_assets_response = client.post(
        url_for("AssetAPI:post"),
        json=post_data,
    )
    print("Server responded with:\n%s" % post_assets_response.json)
    assert post_assets_response.status_code == 201
    assert post_assets_response.json["latitude"] == 30.1

    asset: GenericAsset = db.session.execute(
        select(GenericAsset).filter_by(name=post_data["name"])
    ).scalar_one_or_none()
    assert asset is not None
    assert asset.latitude == 30.1


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_edit_an_asset(client, setup_api_fresh_test_data, requesting_user, db):
    with AccountContext("Test Supplier Account") as supplier:
        existing_asset = supplier.generic_assets[0]

    post_data = dict(latitude=10)
    edit_asset_response = client.patch(
        url_for("AssetAPI:patch", id=existing_asset.id),
        json=post_data,
    )
    assert edit_asset_response.status_code == 200
    updated_asset = db.session.execute(
        select(GenericAsset).filter_by(id=existing_asset.id)
    ).scalar_one_or_none()
    assert updated_asset.latitude == 10  # changed value
    assert updated_asset.longitude == existing_asset.longitude
    assert updated_asset.name == existing_asset.name


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_delete_an_asset(client, setup_api_fresh_test_data, requesting_user, db):
    with AccountContext("Test Prosumer Account") as prosumer:
        existing_asset_id = prosumer.generic_assets[0].id

    delete_asset_response = client.delete(
        url_for("AssetAPI:delete", id=existing_asset_id),
    )
    assert delete_asset_response.status_code == 204
    deleted_asset = db.session.execute(
        select(GenericAsset).filter_by(id=existing_asset_id)
    ).scalar_one_or_none()
    assert deleted_asset is None


@pytest.mark.parametrize(
    "requesting_user, sensor_index, data_unit, data_resolution, price, expected_event_values, expected_status",
    [
        (
            "test_prosumer_user_2@seita.nl",
            1,
            "m/s",
            "1h",
            45.3,
            None,
            422,
        ),  # this sensor has unit=kW
        (
            "test_prosumer_user_2@seita.nl",
            2,
            "kWh",
            "1h",
            45.3,
            45.3,
            200,
        ),  # this sensor has unit=kWh
        (
            "test_prosumer_user_2@seita.nl",
            0,
            "kWh",
            "1h",
            45.3,
            0.0453,
            200,
        ),  # this sensor has unit=MW
        (
            "test_prosumer_user_2@seita.nl",
            1,
            "MW",
            "1h",
            2,
            2000,
            200,
        ),  # this sensor has unit=kW
        (
            "test_prosumer_user_2@seita.nl",
            1,
            "kWh",
            "30min",
            10,
            20,
            200,
        ),  # this sensor has unit=kW
    ],
    indirect=["requesting_user"],
)
def test_auth_upload_sensor_data_with_distinct_units(  # TODO: remove auth prefix from function name
    fresh_db,
    client,
    add_battery_assets_fresh_db,
    requesting_user,
    sensor_index,
    data_unit,
    data_resolution,
    price,
    expected_event_values,
    expected_status,
):
    """
    Check if unit validation works fine for sensor data upload.
    The target sensor has a kWh unit and event resolution of 30 minutes.
    Incoming data can differ in both unit and resolution, so we check if the resulting data matches expectations.
    """
    start_date = (
        "2025-01-01T00:10:00+00:00"  # This date would be used to generate CSV content
    )
    test_battery = add_battery_assets_fresh_db["Test battery"]
    sensor = test_battery.sensors[sensor_index]
    csv_content = generate_csv_content(
        start_time_str=start_date,
        num_intervals=4,
        resolution_str=data_resolution,
        price=price,
    )

    import io

    file_obj = io.BytesIO(csv_content.encode("utf-8"))

    response = client.post(
        url_for("SensorAPI:upload_data", id=sensor.id),
        data={"uploaded-files": (file_obj, "data.csv"), "unit": data_unit},
        content_type="multipart/form-data",
    )
    print("Response:\n%s" % response.status_code, expected_status)
    print("Server responded with:\n%s" % response.json)

    assert response.status_code == expected_status

    # fetch the save timedBeliefs and check if they have the right values
    if response.status_code == 200:
        timed_beliefs = fresh_db.session.execute(
            select(TimedBelief)
            .filter(TimedBelief.sensor_id == sensor.id)
            .order_by(TimedBelief.event_start)
        ).scalars()

        beliefs = timed_beliefs.all()

        if data_resolution == "1h":
            assert len(beliefs) == 16
        else:
            assert len(beliefs) == 8
        assert expected_event_values == beliefs[0].event_value
