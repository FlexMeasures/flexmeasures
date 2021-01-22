"""Useful test messages"""


def message_for_get_device_message(
    wrong_id: bool = False, unknown_prices: bool = False
) -> dict:
    message = {
        "type": "GetDeviceMessageRequest",
        "duration": "PT48H",
        "event": "ea1.2018-06.localhost:%s:%s:203:soc",
    }
    if wrong_id:
        message["event"] = "ea1.2018-06.localhost:%s:%s:9999:soc"
    if unknown_prices:
        message[
            "duration"
        ] = "PT1000H"  # We have no beliefs in our test database about prices so far into the future
    return message


def message_for_post_udi_event() -> dict:
    message = {
        "type": "PostUdiEventRequest",
        "event": "ea1.2018-06.io.flexmeasures.company:%s:%s:204:soc",
        "datetime": "2018-09-27T10:00:00+00:00",
        "value": 12.1,
        "unit": "kWh",
    }
    return message
