from flask import url_for
import pytest
from datetime import timedelta
from isodate import parse_datetime

from flexmeasures.api.common.responses import unrecognized_event, unknown_prices
from flexmeasures.api.tests.utils import get_auth_token
from flexmeasures.api.v1_2.tests.utils import (
    message_for_get_device_message,
    message_for_post_udi_event,
)
from flexmeasures.data.models.assets import Asset


@pytest.mark.parametrize("message", [message_for_get_device_message()])
def test_get_device_message(client, message):
    asset = Asset.query.filter(Asset.name == "Test battery").one_or_none()
    message["event"] = message["event"] % (asset.owner_id, asset.id)
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    get_device_message_response = client.get(
        url_for("flexmeasures_api_v1_2.get_device_message"),
        query_string=message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_device_message_response.json)
    assert get_device_message_response.status_code == 200
    assert get_device_message_response.json["type"] == "GetDeviceMessageResponse"
    assert len(get_device_message_response.json["values"]) == 192

    # Test that a shorter planning horizon yields the same result
    message["duration"] = "PT6H"
    get_device_message_response_short = client.get(
        url_for("flexmeasures_api_v1_2.get_device_message"),
        query_string=message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_device_message_response_short.json)
    assert get_device_message_response_short.status_code == 200
    assert (
        get_device_message_response_short.json["values"]
        == get_device_message_response.json["values"][0:24]
    )

    # Test that a much longer planning horizon yields the same result (when there are only 2 days of prices)
    message["duration"] = "PT1000H"
    get_device_message_response_long = client.get(
        url_for("flexmeasures_api_v1_2.get_device_message"),
        query_string=message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    assert (
        get_device_message_response_long.json["values"][0:192]
        == get_device_message_response.json["values"]
    )


def test_get_device_message_mistyped_duration(client):
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    message = message_for_get_device_message()
    asset = Asset.query.filter(Asset.name == "Test battery").one_or_none()
    message["event"] = message["event"] % (asset.owner_id, asset.id)
    message["duration"] = "PTT6H"
    get_device_message_response = client.get(
        url_for("flexmeasures_api_v1_2.get_device_message"),
        query_string=message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_device_message_response.json)
    assert get_device_message_response.status_code == 422
    assert (
        "Cannot parse PTT6H as ISO8601 duration"
        in get_device_message_response.json["message"]["args_and_json"]["duration"][0]
    )


@pytest.mark.parametrize("message", [message_for_get_device_message(wrong_id=True)])
def test_get_device_message_wrong_event_id(client, message):
    asset = Asset.query.filter(Asset.name == "Test battery").one_or_none()
    message["event"] = message["event"] % (asset.owner_id, asset.id)
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    get_device_message_response = client.get(
        url_for("flexmeasures_api_v1_2.get_device_message"),
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


@pytest.mark.parametrize(
    "message", [message_for_get_device_message(unknown_prices=True)]
)
def test_get_device_message_unknown_prices(client, message):
    asset = Asset.query.filter(
        Asset.name == "Test battery with no known prices"
    ).one_or_none()
    message["event"] = message["event"] % (asset.owner_id, asset.id)
    auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
    get_device_message_response = client.get(
        url_for("flexmeasures_api_v1_2.get_device_message"),
        query_string=message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_device_message_response.json)
    assert get_device_message_response.status_code == 400
    assert get_device_message_response.json["type"] == "GetDeviceMessageResponse"
    assert get_device_message_response.json["status"] == unknown_prices()[0]["status"]


@pytest.mark.parametrize("message", [message_for_post_udi_event()])
def test_post_udi_event(app, message):
    auth_token = None
    with app.test_client() as client:
        asset = Asset.query.filter(Asset.name == "Test battery").one_or_none()
        message["event"] = message["event"] % (asset.owner_id, asset.id)
        auth_token = get_auth_token(client, "test_prosumer@seita.nl", "testtest")
        post_udi_event_response = client.post(
            url_for("flexmeasures_api_v1_2.post_udi_event"),
            json=message,
            headers={"Authorization": auth_token},
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
            url_for("flexmeasures_api_v1_2.post_udi_event"),
            json=message,
            headers={"Authorization": auth_token},
        )
        print("Server responded with:\n%s" % post_udi_event_response.json)
        assert post_udi_event_response.status_code == 400
        assert post_udi_event_response.json["type"] == "PostUdiEventResponse"
        assert post_udi_event_response.json["status"] == "OUTDATED_UDI_EVENT"

        message["event"] = message["event"].replace("204", "205")
        post_udi_event_response = client.post(
            url_for("flexmeasures_api_v1_2.post_udi_event"),
            json=message,
            headers={"Authorization": auth_token},
        )
        print("Server responded with:\n%s" % post_udi_event_response.json)
        assert post_udi_event_response.status_code == 200
        assert post_udi_event_response.json["type"] == "PostUdiEventResponse"

    # test database state
    asset = Asset.query.filter(Asset.name == "Test battery").one_or_none()
    assert asset.soc_datetime == next_msg_dt
    assert asset.soc_in_mwh == message["value"] / 1000
    assert asset.soc_udi_event_id == 205
