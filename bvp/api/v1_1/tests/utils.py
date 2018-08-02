"""Useful test messages"""


def message_for_get_prognosis(
    no_horizon: bool = False,
    invalid_horizon=False,
    rolling_horizon=False,
    no_data=False,
    no_resolution=False,
    single_connection=False,
) -> dict:
    message = {
        "type": "GetPrognosisRequest",
        "start": "2015-01-01T00:00:00Z",
        "duration": "PT1H30M",
        "horizon": "R/PT6H",
        "resolution": "PT15M",
        "connections": ["CS 1", "CS 2", "CS 3"],
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
        message["start"] = ("2010-01-01T00:00:00Z",)
    if no_resolution:
        message.pop("resolution", None)
    if single_connection:
        message["connection"] = message["connections"][0]
        message.pop("connections", None)
    return message
