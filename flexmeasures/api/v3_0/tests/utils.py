from flexmeasures import Sensor


def make_sensor_data_request_for_gas_sensor(
    num_values: int = 6, duration: str = "PT1H", unit: str = "m³"
) -> dict:
    """Creates request to post sensor data for a gas sensor.
    This particular gas sensor measures units of m³/h with a 10-minute resolution.
    """
    sensor = Sensor.query.filter(Sensor.name == "some gas sensor").one_or_none()
    message: dict = {
        "type": "PostSensorDataRequest",
        "sensor": f"ea1.2021-01.io.flexmeasures:fm1.{sensor.id}",
        "values": num_values * [-11.28],
        "start": "2021-06-07T00:00:00+02:00",
        "duration": duration,
        "horizon": "PT0H",
        "unit": unit,
    }
    if num_values == 1:
        # flatten [<float>] to <float>
        message["values"] = message["values"][0]
    return message


def get_asset_post_data(account_id: int = 1, asset_type_id: int = 1) -> dict:
    post_data = {
        "name": "Test battery 2",
        "latitude": 30.1,
        "longitude": 100.42,
        "generic_asset_type_id": asset_type_id,
        "account_id": account_id,
    }
    return post_data


def message_for_trigger_schedule(
    unknown_prices: bool = False,
    with_targets: bool = False,
    deprecated_format_pre012: bool = False,
) -> dict:
    message = {
        "start": "2015-01-01T00:00:00+01:00",
        "prior": "2015-01-04T00:00:00+01:00",
    }
    if unknown_prices:
        message[
            "start"
        ] = "2040-01-01T00:00:00+01:00"  # We have no beliefs in our test database about 2040 prices
        message["prior"] = "2040-01-04T00:00:00+01:00"

    if deprecated_format_pre012:
        message["soc-at-start"] = 12.1
        message["soc-unit"] = "kWh"
    else:
        message["flex_model"] = {}
        message["flex_model"]["soc_at_start"] = 12.1
        message["flex_model"]["soc_unit"] = "kWh"
    if with_targets:
        targets = [{"value": 25, "datetime": "2015-01-02T23:00:00+01:00"}]
        if deprecated_format_pre012:
            message["soc-targets"] = targets
        else:
            message["flex_model"]["soc_targets"] = targets
    return message
