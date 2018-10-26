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
        message["horizon"] = "T6H"
    elif rolling_horizon:
        message["horizon"] = "R/PT6H"
    if no_data:
        message["start"] = ("2010-01-01T00:00:00Z",)
    if no_resolution:
        message.pop("resolution", None)
    if single_connection:
        message["connection"] = message["connections"][0]
        message.pop("connections", None)
    return message


def message_for_post_price_data(invalid_unit: bool = False) -> dict:
    message = {
        "type": "PostPriceDataRequest",
        "market": "ea1.2018-06.localhost:5000:epex_da",
        "values": [
            52.37,
            51.14,
            49.09,
            48.35,
            48.47,
            49.98,
            58.7,
            67.76,
            69.21,
            70.26,
            70.46,
            70,
            70.7,
            70.41,
            70,
            64.53,
            65.92,
            69.72,
            70.51,
            75.49,
            70.35,
            70.01,
            66.98,
            58.61,
        ],
        "start": "2015-01-01T15:00:00+09:00",
        "duration": "PT24H",
        "horizon": "PT35H",
        "unit": "EUR/MWh",
    }
    if invalid_unit:
        message["unit"] = "KRW/kWh"
    return message


def message_for_post_weather_data(
    invalid_unit: bool = False, temperature: bool = False
) -> dict:
    message = {
        "type": "PostWeatherDataRequest",
        "groups": [
            {
                "sensor": "ea1.2018-06.localhost:5000:wind_speed:33.4843866:126",
                "values": [20.04, 20.23, 20.41, 20.51, 20.55, 20.57],
            }
        ],
        "start": "2015-01-01T15:00:00+09:00",
        "duration": "PT1H30M",
        "horizon": "PT3H",
        "unit": "m/s",
    }
    if temperature:
        message["groups"][0][
            "sensor"
        ] = "ea1.2018-06.localhost:5000:temperature:33.4843866:126"
        if not invalid_unit:
            message["unit"] = "°C"  # Right unit for temperature
    elif invalid_unit:
        message["unit"] = "°C"  # Wrong unit for wind speed
    return message
