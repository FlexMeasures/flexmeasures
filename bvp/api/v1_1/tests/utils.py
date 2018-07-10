"""Useful test messages"""


def message_for_get_prognosis(
    no_horizon: bool = False,
    invalid_horizon=False,
    rolling_horizon=False,
    no_data=False,
    no_resolution=False,
) -> dict:
    message = {
        "type": "GetPrognosisRequest",
        "start": "2015-01-01T00:00:00Z",
        "duration": "PT1H30M",
        "horizon": "PT6H",
        "resolution": "PT15M",
        "connection": "CS 1",
        "unit": "MW",
    }
    if no_horizon:
        message.pop("horizon", None)
        message.pop(
            "start", None
        )  # Otherwise, the server will determine the horizon based on when the API endpoint was called
    elif invalid_horizon:
        message["horizon"] = "T6h"
    elif rolling_horizon:
        message["horizon"] = "R/PT6h"
    if no_data:
        message["connection"] = "CS 2"
    if no_resolution:
        message.pop("resolution", None)
    return message
