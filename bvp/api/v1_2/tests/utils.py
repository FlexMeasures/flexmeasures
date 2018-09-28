"""Useful test messages"""


def message_for_get_device_message(wrong_id: bool = False) -> dict:
    message = {
        "type": "GetDeviceMessageRequest",
        "start": "2015-01-01T00:00:00Z",
        "duration": "PT24H",
        "event": "ea1.2018-06.localhost:5000:%s:%s:203:soc",
    }
    if wrong_id:
        message["event"] = "ea1.2018-06.localhost:5000:%s:%s:9999:soc"
    return message


def message_for_post_udi_event() -> dict:
    message = {
        "type": "PostUdiEventRequest",
        "event": "ea1.2018-06.com.a1-bvp.play:%s:%s:204:soc",
        "datetime": "2018-09-27T10:00:00+00:00",
        "value": 12.1,
        "unit": "kWh",
    }
    return message
