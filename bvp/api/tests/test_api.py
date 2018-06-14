import json
import requests
import pytest
from typing import List

from flask import url_for
from flask_security import SQLAlchemySessionUserDatastore
from flask_security.utils import hash_password


from bvp.app import create as create_app


@pytest.fixture(scope="session")
def app(request):
    test_app = create_app(env="testing")

    # Establish an application context before running the tests.
    ctx = test_app.app_context()
    ctx.push()

    yield test_app

    ctx.pop()


@pytest.fixture(scope="session")
def set_up_test_data(app):
    """
    Assuming the database is depopulated, create test roles, users and assets, and clean up afterwards.
    """
    from bvp.data.config import db
    from bvp.data.models.assets import Asset, AssetType
    from bvp.data.models.assets import Power
    from bvp.data.models.user import User, Role

    # Create 1 test role

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    test_prosumer_role = user_datastore.create_role(
        name="prosumer",
        description="A Prosumer with access to some solar assets and Prosumer controls.",
    )

    # Create 2 test users

    test_user = user_datastore.create_user(
        username="test user",
        email="test_user@seita.nl",
        password=hash_password("testtest"),
    )
    test_prosumer = user_datastore.create_user(
        username="test prosumer",
        email="test_prosumer@seita.nl",
        password=hash_password("testtest"),
    )
    user_datastore.add_role_to_user(test_prosumer, test_prosumer_role)

    # Create 3 test assets

    test_asset_type = AssetType(name="test-type")
    db.session.add(test_asset_type)
    asset_names = ["test-asset-1", "test-asset-2", "test-asset-3"]
    assets: List[Asset] = []
    for asset_name in asset_names:
        asset = Asset(
            name=asset_name,
            asset_type_name="test-type",
            capacity_in_mw=1,
            latitude=100,
            longitude=100,
        )
        asset.owner = test_prosumer
        assets.append(asset)
        db.session.add(asset)

    db.session.commit()

    yield

    print("Cleaning up assets and users ...")
    try:
        db.session.query(Power).delete()
        db.session.query(Asset).delete()
        db.session.query(AssetType).delete()
        roles = db.session.query(Role).all()
        for role in roles:
            db.session.delete(role)
        users = db.session.query(User).all()
        for user in users:
            db.session.delete(user)
        db.session.commit()
    except Exception as e:
        print(e)
        raise


def test_api_login_service_responds(app, set_up_test_data, client):

    # get auth token
    auth_data = json.dumps({"email": "test_user@seita.nl", "password": "testtest"})
    auth_response = client.post(
        url_for("bvp_api.request_auth_token"),
        data=auth_data,
        headers={"content-type": "application/json"},
    )
    auth_token = auth_response.json["auth_token"]

    # get meter data
    get_meter_data_response = client.get(
        url_for("bvp_api.get_meter_data"),
        query_string={
            "start": "2016-05-01T12:45:00Z",
            "duration": "PT1H30M",
            "connection": "test-asset-1",
            "unit": "MW",
        },
        headers={"Authentication-Token": auth_token},
    )
    assert get_meter_data_response.status_code == 401

    # get auth token
    auth_data = json.dumps({"email": "test_prosumer@seita.nl", "password": "testtest"})
    auth_response = client.post(
        url_for("bvp_api.request_auth_token"),
        data=auth_data,
        headers={"content-type": "application/json"},
    )
    auth_token = auth_response.json["auth_token"]

    # post meter data
    test_values_for_asset_1_and_2 = [306.66, 306.66, 0, 0, 306.66, 306.66]
    test_values_for_asset_3 = [306.66, 0, 0, 0, 306.66, 306.66]
    post_meter_data_response = client.post(
        url_for("bvp_api.post_meter_data"),
        data=json.dumps(
            {
                "type": "PostMeterDataRequest",
                "groups": [
                    {
                        "connections": [
                            "ea1.2018-06.com.bvp.api:45:test-asset-1",
                            "ea1.2018-06.com.bvp.api:45:test-asset-2",
                        ],
                        "values": test_values_for_asset_1_and_2,
                    },
                    {
                        "connection": "ea1.2018-06.com.bvp.api:45:test-asset-3",
                        "values": test_values_for_asset_3,
                    },
                ],
                "start": "2016-05-01T12:45:00Z",
                "duration": "PT1H30M",
                "unit": "MW",
            }
        ),
        headers={
            "content-type": "application/json",
            "Authentication-Token": auth_token,
        },
    )
    assert post_meter_data_response.status_code == 200

    # get meter data
    get_meter_data_response = client.get(
        url_for("bvp_api.get_meter_data"),
        query_string={
            "start": "2016-05-01T12:45:00Z",
            "duration": "PT1H30M",
            "connection": "test-asset-1",
            "unit": "MW",
        },
        headers={"Authentication-Token": auth_token},
    )
    assert get_meter_data_response.status_code == 200
    assert get_meter_data_response.json["values"] == test_values_for_asset_1_and_2
