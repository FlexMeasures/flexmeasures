from __future__ import annotations

import pytest
import math
import io

from flask import url_for
from sqlalchemy import select, func

from flexmeasures.data.models.time_series import TimedBelief
from flexmeasures import Sensor
from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.v3_0.tests.utils import get_sensor_post_data
from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.schemas.sensors import SensorSchema
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.tests.utils import QueryCounter
from flexmeasures.utils.unit_utils import is_valid_unit


sensor_schema = SensorSchema()


@pytest.mark.parametrize(
    "requesting_user, search_by, search_value, exp_sensor_name, exp_num_results, include_consultancy_clients, use_pagination, expected_status_code, filter_account_id, filter_asset_id, asset_id_of_of_first_sensor_result",
    [
        (
            "test_supplier_user_4@seita.nl",
            "unit",
            "°C",
            "some temperature sensor",
            2,
            True,
            False,
            200,
            None,
            5,
            None,
        ),
        (
            "test_prosumer_user@seita.nl",
            None,
            None,
            "power",
            2,
            False,
            False,
            200,
            None,
            7,
            8,  # We test that the endpoint returns the sensor on a battery asset (ID: 8) while we filter for the building asset (ID: 7) that includes it
        ),
        (
            "test_supplier_user_4@seita.nl",
            "unit",
            "m³/h",
            "some gas sensor",
            1,
            True,
            False,
            200,
            None,
            5,
            None,
        ),
        (
            "test_supplier_user_4@seita.nl",
            None,
            None,
            None,
            None,
            None,
            None,
            422,  # Error expected due to both asset_id and account_id being provided
            1,
            5,
            None,
        ),
        (
            "test_dummy_account_admin@seita.nl",
            None,
            None,
            None,
            None,
            None,
            None,
            403,  # Error expected as the user lacks access to the specified asset
            None,
            5,
            None,
        ),
        (
            "test_supplier_user_4@seita.nl",
            None,
            None,
            None,
            None,
            None,
            None,
            403,  # Error expected as the user lacks access to the specified account
            1,
            None,
            None,
        ),
        (
            "test_supplier_user_4@seita.nl",
            None,
            None,
            "some temperature sensor",
            3,
            True,
            True,
            200,
            None,
            5,
            None,
        ),
        (
            "test_supplier_user_4@seita.nl",
            "filter",
            "'some temperature sensor'",
            "some temperature sensor",
            1,
            False,
            False,
            200,
            None,
            5,
            None,
        ),
    ],
    indirect=["requesting_user"],
)
def test_fetch_sensors(
    client,
    setup_api_test_data,
    add_battery_assets,
    requesting_user,
    search_by,
    search_value,
    exp_sensor_name,
    exp_num_results,
    include_consultancy_clients,
    use_pagination,
    expected_status_code,
    filter_account_id,
    filter_asset_id,
    asset_id_of_of_first_sensor_result,
):
    """
    Retrieve all sensors.

    Our user here is admin, so is allowed to see all sensors.
    Pagination is tested only in passing, we should test filtering and page > 1

    The `filter_asset_id` specifies the asset_id to filter for.

    The `asset_id_of_of_first_sensor_result` specifies the asset_id of the first sensor
    in the result list. This sensors is expected to be from a child asset of the asset
    specified in `filter_asset_id`.

    The `filter_account_id` specifies the account_id to filter for.

    `check_errors` is used to test the error handling of the endpoint.
    """
    query = {search_by: search_value}

    if use_pagination:
        query["page"] = 1

    if search_by == "unit":
        query["unit"] = search_value
    elif search_by == "filter":
        query["filter"] = search_value

    if include_consultancy_clients:
        query["include_consultancy_clients"] = True

    if filter_account_id:
        query["account_id"] = filter_account_id

    if filter_asset_id:
        query["asset_id"] = filter_asset_id

    response = client.get(
        url_for("SensorAPI:index"),
        query_string=query,
    )

    print("Server responded with:\n%s" % response.json)

    assert response.status_code == expected_status_code
    if expected_status_code == 200:
        if use_pagination:
            assert isinstance(response.json["data"][0], dict)
            assert is_valid_unit(response.json["data"][0]["unit"])
            assert response.json["num-records"] == exp_num_results
            assert response.json["filtered-records"] == exp_num_results
        else:
            assert isinstance(response.json, list)
            assert is_valid_unit(response.json[0]["unit"])
            assert response.json[0]["name"] == exp_sensor_name
            assert len(response.json) == exp_num_results

            if asset_id_of_of_first_sensor_result is not None:
                assert (
                    response.json[0]["generic_asset_id"]
                    == asset_id_of_of_first_sensor_result
                )
            elif filter_asset_id:
                assert response.json[0]["generic_asset_id"] == filter_asset_id

            if search_by == "unit":
                assert response.json[0]["unit"] == search_value


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_fetch_one_sensor(
    client, setup_api_test_data: dict[str, Sensor], requesting_user, db
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
    asset = db.session.get(GenericAsset, response.json["generic_asset_id"])
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
def test_post_a_sensor(client, setup_api_test_data, requesting_user, db):
    post_data = get_sensor_post_data()
    response = client.post(
        url_for("SensorAPI:post"),
        json=post_data,
    )
    print("Server responded with:\n%s" % response.json)
    assert response.status_code == 201
    assert response.json["name"] == "power"
    assert response.json["event_resolution"] == "PT1H"
    assert response.json["generic_asset_id"] == post_data["generic_asset_id"]

    sensor: Sensor = db.session.execute(
        select(Sensor).filter_by(name="power", unit="kWh")
    ).scalar_one_or_none()

    assert sensor is not None
    assert sensor.unit == "kWh"
    assert sensor.attributes["capacity_in_mw"] == 0.0074

    assert db.session.execute(
        select(AssetAuditLog).filter_by(
            affected_asset_id=post_data["generic_asset_id"],
            event=f"Created sensor '{sensor.name}': {sensor.id}",
            active_user_id=requesting_user.id,
            active_user_name=requesting_user.username,
        )
    ).scalar_one_or_none()


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_upload_csv_file(client, requesting_user):
    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")
    csv_content = """event_start,event_value
2022-12-16T05:11:00Z,4
2022-12-16T06:11:00Z,2
2022-12-16T07:11:00Z,6
2022-12-16T08:11:00Z,3
2022-12-16T09:11:00Z,8
2022-12-16T10:11:00Z,4
"""
    file = (io.BytesIO(csv_content.encode("utf-8")), "test.csv")

    # Match what the schema expects
    data = {"uploaded-files": file}

    response = client.post(
        url_for("SensorAPI:upload_data", id=1),
        data=data,
        content_type="multipart/form-data",
        headers={"Authorization": auth_token},
    )
    assert response.status_code == 200 or response.status_code == 400


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_upload_excel_file(client, requesting_user):
    import openpyxl

    auth_token = get_auth_token(client, "test_admin_user@seita.nl", "testtest")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["event_start", "event_value"])
    ws.append(["2022-12-16T05:11:00Z", 4])
    ws.append(["2022-12-16T06:11:00Z", 2])
    ws.append(["2022-12-16T07:11:00Z", 6])
    ws.append(["2022-12-16T08:11:00Z", 3])
    ws.append(["2022-12-16T09:11:00Z", 8])
    ws.append(["2022-12-16T10:11:00Z", 4])
    file_stream = io.BytesIO()
    wb.save(file_stream)
    file_stream.seek(0)

    data = {"uploaded-files": (file_stream, "test.xlsx")}

    response = client.post(
        url_for("SensorAPI:upload_data", id=1),
        data=data,
        content_type="multipart/form-data",
        headers={"Authorization": auth_token},
    )
    assert response.status_code == 200 or response.status_code == 400


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
def test_patch_sensor(client, setup_api_test_data, requesting_user, db):
    sensor = db.session.execute(
        select(Sensor).filter_by(name="some gas sensor")
    ).scalar_one_or_none()
    response = client.patch(
        url_for("SensorAPI:patch", id=sensor.id),
        json={
            "name": "Changed name",
            "attributes": '{"test_attribute": "test_attribute_value"}',
        },
    )
    assert response.json["name"] == "Changed name"
    new_sensor = db.session.execute(
        select(Sensor).filter_by(name="Changed name")
    ).scalar_one_or_none()
    assert new_sensor.name == "Changed name"
    assert (
        db.session.execute(
            select(Sensor).filter_by(name="some gas sensor")
        ).scalar_one_or_none()
        is None
    )
    assert new_sensor.attributes["test_attribute"] == "test_attribute_value"

    audit_log_event = (
        f"Updated sensor 'some gas sensor': {sensor.id}. Updated fields: Field name: name, Old value: some gas sensor, New value: Changed name; Field name: attributes, "
        + "Old value: {}, New value: {'test_attribute': 'test_attribute_value'}"
    )
    assert db.session.execute(
        select(AssetAuditLog).filter_by(
            event=audit_log_event,
            active_user_id=requesting_user.id,
            active_user_name=requesting_user.username,
            affected_asset_id=sensor.generic_asset_id,
        )
    ).scalar_one_or_none()


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
    client, setup_api_test_data, attribute, value, requesting_user, db
):
    """Test to change the generic_asset_id that should not be allowed.
    The generic_asset_id is excluded in the partial_sensor_schema"""
    sensor = db.session.execute(
        select(Sensor).filter_by(name="some temperature sensor")
    ).scalar_one_or_none()
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
def test_patch_sensor_non_admin(client, setup_api_test_data, requesting_user, db):
    """Try to change the name of a sensor with a non admin account"""

    sensor = db.session.execute(
        select(Sensor).filter_by(name="some temperature sensor")
    ).scalar_one_or_none()
    response = client.patch(
        url_for("SensorAPI:patch", id=sensor.id),
        json={
            "name": "try to change the name",
        },
    )

    assert response.status_code == 403
    assert response.json["status"] == "INVALID_SENDER"


@pytest.mark.parametrize("requesting_user", ["test_admin_user@seita.nl"], indirect=True)
def test_delete_a_sensor(client, setup_api_test_data, requesting_user, db):
    existing_sensor = setup_api_test_data["some temperature sensor"]
    existing_sensor_id = existing_sensor.id
    sensor_data = db.session.scalars(
        select(TimedBelief).filter(TimedBelief.sensor_id == existing_sensor_id)
    ).all()
    sensor_count = db.session.scalar(select(func.count()).select_from(Sensor))

    assert isinstance(sensor_data[0].event_value, float)

    delete_sensor_response = client.delete(
        url_for("SensorAPI:delete", id=existing_sensor_id),
    )
    assert delete_sensor_response.status_code == 204
    deleted_sensor = db.session.get(Sensor, existing_sensor_id)
    assert deleted_sensor is None
    assert (
        db.session.scalars(
            select(TimedBelief).filter(TimedBelief.sensor_id == existing_sensor_id)
        ).all()
        == []
    )
    assert (
        db.session.scalar(select(func.count()).select_from(Sensor)) == sensor_count - 1
    )

    assert db.session.execute(
        select(AssetAuditLog).filter_by(
            affected_asset_id=existing_sensor.generic_asset_id,
            event=f"Deleted sensor '{existing_sensor.name}': {existing_sensor.id}",
            active_user_id=requesting_user.id,
            active_user_name=requesting_user.username,
        )
    ).scalar_one_or_none()


@pytest.mark.parametrize(
    "requesting_user", ["test_supplier_user_4@seita.nl"], indirect=True
)
def test_fetch_sensor_stats(
    client, setup_api_test_data: dict[str, Sensor], requesting_user, db
):
    # gas sensor is set up in add_gas_measurements
    sensor_id = 1
    with QueryCounter(db.session.connection()) as counter1:
        response = client.get(
            url_for("SensorAPI:get_stats", id=sensor_id),
        )
        print("Server responded with:\n%s" % response.json)
        assert response.status_code == 200
        response_content = response.json

        del response_content["status"]
        assert sorted(list(response_content.keys())) == [
            "Other source",
            "Test Supplier User",
        ]
        for source, record in response_content.items():
            assert record["First event start"] == "2021-05-01T22:00:00+00:00"
            assert record["Last event end"] == "2021-05-01T22:30:00+00:00"
            assert record["Min value"] == 91.3
            assert record["Max value"] == 92.1
            if source == "Test Supplier User":
                # values are: 91.3, 91.7, 92.1
                sum_values = 275.1
                count_values = 3
            else:
                # values are: 91.3, NaN, 92.1
                sum_values = 183.4
                count_values = 3
            mean_value = 91.7
            assert math.isclose(
                record["Mean value"], mean_value, rel_tol=1e-5
            ), f"mean_value is close to {mean_value}"
            assert math.isclose(
                record["Sum over values"], sum_values, rel_tol=1e-5
            ), f"sum_values is close to {sum_values}"
            assert record["Number of values"] == count_values

    with QueryCounter(db.session.connection()) as counter2:
        response = client.get(
            url_for("SensorAPI:get_stats", id=sensor_id),
        )
        print("Server responded with:\n%s" % response.json)
        assert response.status_code == 200

    # Check stats cache works and stats query is executed only once
    assert counter1.count == counter2.count + 1
