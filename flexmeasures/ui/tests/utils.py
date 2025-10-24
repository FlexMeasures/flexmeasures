from __future__ import annotations

import copy
import json
from sqlalchemy import select

from flask import url_for

from flexmeasures.data.models.time_series import Sensor


def login(the_client, email, password):
    auth_data = dict(email=email, password=password)
    login_response = the_client.post(
        url_for("security.login"), data=auth_data, follow_redirects=True
    )
    assert login_response.status_code == 200
    assert b"Please log in" not in login_response.data
    return login_response


def logout(client):
    return client.get(url_for("security.logout"), follow_redirects=True)


def mock_asset_data(
    asset_id: int = 2,
    account_id: int = 1,
    as_list: bool = True,
    multiple: bool = False,
) -> dict | list[dict]:
    """
    Mock response from asset API.
    Does not mock output of paginated assets endpoint!
    """
    asset = dict(
        id=asset_id,
        name="TestAsset",
        generic_asset_type_id=1,
        account_id=int(account_id),
        latitude=70.4,
        longitude=30.9,
    )
    if as_list:
        asset_list = [asset]
        if multiple:
            asset2 = copy.deepcopy(asset)
            asset2["name"] = "TestAsset2"
            asset2["id"] += 1
            asset_list.append(asset2)
        return asset_list
    return asset


def mock_asset_data_with_kpis(
    db,
    asset_id: int = 1,
    account_id: int = 1,
    as_list: bool = True,
    multiple: bool = False,
) -> dict | list[dict]:
    asset = mock_asset_data(
        asset_id=asset_id, account_id=account_id, as_list=as_list, multiple=multiple
    )
    sensor: Sensor = db.session.execute(
        select(Sensor).filter_by(event_resolution="PT24H")
    ).scalar_one_or_none()

    if not sensor:
        # Create a sensor first with PT24H
        sensor = Sensor(
            name="KPI sensor",
            generic_asset_id=asset["id"],
            event_resolution="PT24H",
            unit="kWh",
            attributes={},
        )
        db.session.add(sensor)
        db.session.flush()
    sensors_to_show_as_kpis = [
        {
            "title": "My KPIs",
            "sensor": sensor.id,
            "function": "sum",
        }
    ]
    asset["sensors_to_show_as_kpis"] = json.dumps(sensors_to_show_as_kpis)
    return asset


def mock_asset_data_as_form_input(api_data: dict) -> dict:
    form_input = copy.deepcopy(api_data)
    form_input["account"] = api_data["account_id"]
    return form_input


def mock_account_response(
    account_id: int = 1,
    account_name: str = "test_account",
    account_roles: list = [{"id": 1, "name": "Prosumer"}],
    as_list: bool = True,
    multiple: bool = False,
) -> dict | list[dict]:
    account = dict(
        id=account_id,
        name=account_name,
        account_roles=account_roles,
    )
    if as_list:
        account_list = [account]
        if multiple:
            account2 = copy.deepcopy(account)
            account2["id"] = 2
            account2["name"] = "test_account2"
            account2["account_roles"] = []
            account_list.append(account2)
        return account_list
    return account
