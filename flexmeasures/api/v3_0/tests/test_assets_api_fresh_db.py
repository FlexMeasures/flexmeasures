import io

from flask import url_for
import pytest
from sqlalchemy import select
from datetime import timedelta

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
    "requesting_user, sensor_index, data_unit, data_resolution, data_values, expected_event_values, expected_status",
    [
        (
            "test_prosumer_user_2@seita.nl",
            1,  # this sensor has unit=kW, res=00:15
            "m/s",
            timedelta(hours=1),
            [45.3, 45.3],
            None,
            422,  # units not convertible
        ),
        (
            "test_prosumer_user_2@seita.nl",
            2,  # this sensor has unit=kWh, res=01:00
            "kWh",
            timedelta(hours=1),
            [45.3] * 4,
            [45.3] * 4,  # same unit and resolution - values stay the same
            200,
        ),
        (
            "test_prosumer_user_2@seita.nl",
            0,  # this sensor has unit=MW, res=00:15
            "kWh",
            timedelta(hours=1),
            [45.3] * 4,
            [45.3 / 1000.0]
            * 4
            * 4,  # values: / 1000 due to kW(h)->MW, number *4 due to h->15min
            200,
        ),
        (
            "test_prosumer_user_2@seita.nl",
            1,  # this sensor has unit=kW, res=00:15
            "MW",
            timedelta(hours=1),
            [2] * 6,
            [2 * 1000]
            * 6
            * 4,  # both power units, so 2 MW = 2000 kW, number *4 due to h->15min
            200,
        ),
        (
            "test_prosumer_user_2@seita.nl",
            1,  # this sensor has unit=kW, res=00:15
            "kWh",
            timedelta(minutes=30),
            [10] * 12,
            [10 * 2]
            * 12
            * 2,  # 10 kWh per half hour = 20 kW power, number *2 due to 30min->15min
            200,
        ),
        (
            "test_prosumer_user_2@seita.nl",
            2,  # this sensor has unit=kWh, res=01:00
            "kWh",
            timedelta(minutes=30),
            [10, 20, 20, 40],
            [
                15,
                30,
            ],  # we make (10/2 + 20/2) the first hour, and (20/2 + 40/2) the second hour
            200,
        ),
        (
            "test_prosumer_user_2@seita.nl",
            2,  # this sensor has unit=kWh, res=01:00
            "kW",
            timedelta(minutes=30),
            [20, 40, 40, 80],
            [
                15,
                30,
            ],  # we make (10/2 + 20/2) the first hour, and (20/2 + 40/2) the second hour
            200,
        ),
    ],
    indirect=["requesting_user"],
)
def test_upload_sensor_data_with_distinct_to_from_units_and_target_resolutions(
    fresh_db,
    client,
    add_battery_assets_fresh_db,
    requesting_user,
    sensor_index,
    data_unit,
    data_resolution,
    data_values,
    expected_event_values,
    expected_status,
):
    """
    Check if unit validation works fine for sensor data upload.
    The target sensors can have different units and resolution,
    and the incoming data can also have differing resolutions and declared unit.
    This test needs to check if the resulting data matches expectations.
    """
    start_date = (
        "2025-01-01T00:10:00+00:00"  # This date would be used to generate CSV content
    )
    test_battery = add_battery_assets_fresh_db["Test battery"]
    sensor = test_battery.sensors[sensor_index]
    num_test_intervals = len(data_values)
    print(
        f"Uploading data to sensor '{sensor.name}' with unit={sensor.unit} and resolution={sensor.event_resolution}."
    )
    print(f"Data unit is {data_unit} and resolution is {data_resolution}")

    csv_content = generate_csv_content(
        start_time_str=start_date,
        interval=data_resolution,
        values=data_values,
    )
    print("Generated CSV content:")
    print(csv_content)
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

        expected_num_beliefs = num_test_intervals * (
            data_resolution / sensor.event_resolution
        )
        print(
            f"Fetched {len(beliefs)} beliefs from the database, expecting {expected_num_beliefs}."
        )
        assert len(beliefs) == expected_num_beliefs
        assert expected_event_values == [b.event_value for b in beliefs]
