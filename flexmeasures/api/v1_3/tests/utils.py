"""Useful test messages"""


def message_for_get_device_message(
    wrong_id: bool = False, unknown_prices: bool = False
) -> dict:
    message = {
        "type": "GetDeviceMessageRequest",
        "duration": "PT48H",
        "event": "ea1.2018-06.localhost:%s:%s:204:soc",
    }
    if wrong_id:
        message["event"] = "ea1.2018-06.localhost:%s:%s:9999:soc"
    if unknown_prices:
        message[
            "duration"
        ] = "PT1000H"  # We have no beliefs in our test database about prices so far into the future
    return message


def message_for_post_udi_event(
    unknown_prices: bool = False,
    targets: bool = False,
) -> dict:
    message = {
        "type": "PostUdiEventRequest",
        "event": "ea1.2018-06.localhost:%s:%s:204:soc",
        "datetime": "2015-01-01T00:00:00+00:00",
        "value": 12.1,
        "unit": "kWh",
    }
    if targets:
        message["event"] = message["event"] + "-with-targets"
        message["targets"] = [{"value": 25, "datetime": "2015-01-02T23:00:00+00:00"}]
    if unknown_prices:
        message[
            "datetime"
        ] = "2040-01-01T00:00:00+00:00"  # We have no beliefs in our test database about 2040 prices
    return message
