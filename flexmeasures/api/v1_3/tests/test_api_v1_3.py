from flask import url_for
import pytest

from flexmeasures.api.common.responses import unrecognized_event
from flexmeasures.api.tests.utils import check_deprecation, get_auth_token
from flexmeasures.api.v1_3.tests.utils import message_for_get_device_message
from flexmeasures.data.models.time_series import Sensor


@pytest.mark.parametrize("message", [message_for_get_device_message(wrong_id=True)])
def test_get_device_message_wrong_event_id(client, message):
    sensor = Sensor.query.filter(Sensor.name == "Test battery").one_or_none()
    message["event"] = message["event"] % sensor.id
    auth_token = get_auth_token(client, "test_prosumer_user@seita.nl", "testtest")
    get_device_message_response = client.get(
        url_for("flexmeasures_api_v1_3.get_device_message"),
        query_string=message,
        headers={"content-type": "application/json", "Authorization": auth_token},
    )
    print("Server responded with:\n%s" % get_device_message_response.json)
    check_deprecation(get_device_message_response)
    assert get_device_message_response.status_code == 400
    assert get_device_message_response.json["type"] == "GetDeviceMessageResponse"
    assert (
        get_device_message_response.json["status"]
        == unrecognized_event(9999, "soc")[0]["status"]
    )
