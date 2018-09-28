from flask import url_for
import pytest
import json
from datetime import timedelta
from isodate import parse_datetime

from bvp.api.common.responses import unrecognized_event
from bvp.api.tests.utils import get_auth_token
from bvp.api.v1_2.tests.utils import (
    message_for_get_device_message,
    message_for_post_udi_event,
)
from bvp.data.models.assets import Asset


@pytest.mark.parametrize("message", [message_for_get_device_message()])
def test_get_device_message(client, message):
    asset = Asset.query.filter(Asset.name == "Test battery").one_or_none()
    message["event"] = message["event"] % (asset.owner_id, asset.id)
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    get_device_message_response = client.get(
        url_for("bvp_api_v1_2.get_device_message"),
        query_string=message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_device_message_response.json)
    assert get_device_message_response.status_code == 200
    assert get_device_message_response.json["type"] == "GetDeviceMessageResponse"
    assert len(get_device_message_response.json["values"]) == 96


@pytest.mark.parametrize("message", [message_for_get_device_message(wrong_id=True)])
def test_get_device_message_wrong_event_id(client, message):
    asset = Asset.query.filter(Asset.name == "Test battery").one_or_none()
    message["event"] = message["event"] % (asset.owner_id, asset.id)
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    get_device_message_response = client.get(
        url_for("bvp_api_v1_2.get_device_message"),
        query_string=message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_device_message_response.json)
    assert get_device_message_response.status_code == 400
    assert get_device_message_response.json["type"] == "GetDeviceMessageResponse"
    assert (
        get_device_message_response.json["status"]
        == unrecognized_event(9999, "soc")[0]["status"]
    )


@pytest.mark.parametrize("message", [message_for_post_udi_event()])
def test_post_udi_event(app, message):
    auth_token = None
    with app.test_client() as client:
        asset = Asset.query.filter(Asset.name == "Test battery").one_or_none()
        message["event"] = message["event"] % (asset.owner_id, asset.id)
        auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
        post_udi_event_response = client.post(
            url_for("bvp_api_v1_2.post_udi_event"),
            data=json.dumps(message),
            headers={"content-type": "application/json", "Authorization": auth_token},
        )
        print("Server responded with:\n%s" % post_udi_event_response.json)
        assert post_udi_event_response.status_code == 200
        assert post_udi_event_response.json["type"] == "PostUdiEventResponse"

    msg_dt = parse_datetime(message["datetime"])

    # test database state
    asset = Asset.query.filter(Asset.name == "Test battery").one_or_none()
    assert asset.soc_datetime == msg_dt
    assert asset.soc_in_mwh == message["value"] / 1000
    assert asset.soc_udi_event_id == 204

    # sending again results in an error, unless we increase the event ID
    with app.test_client() as client:
        next_msg_dt = msg_dt + timedelta(minutes=5)
        message["datetime"] = next_msg_dt.strftime("%Y-%m-%dT%H:%M:%S.%f%z")
        post_udi_event_response = client.post(
            url_for("bvp_api_v1_2.post_udi_event"),
            data=json.dumps(message),
            headers={"content-type": "application/json", "Authorization": auth_token},
        )
        print("Server responded with:\n%s" % post_udi_event_response.json)
        assert post_udi_event_response.status_code == 400
        assert post_udi_event_response.json["type"] == "PostUdiEventResponse"
        assert post_udi_event_response.json["status"] == "OUTDATED_UDI_EVENT"

        message["event"] = message["event"].replace("204", "205")
        post_udi_event_response = client.post(
            url_for("bvp_api_v1_2.post_udi_event"),
            data=json.dumps(message),
            headers={"content-type": "application/json", "Authorization": auth_token},
        )
        print("Server responded with:\n%s" % post_udi_event_response.json)
        assert post_udi_event_response.status_code == 200
        assert post_udi_event_response.json["type"] == "PostUdiEventResponse"

    # test database state
    asset = Asset.query.filter(Asset.name == "Test battery").one_or_none()
    assert asset.soc_datetime == next_msg_dt
    assert asset.soc_in_mwh == message["value"] / 1000
    assert asset.soc_udi_event_id == 205
