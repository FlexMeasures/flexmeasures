from sqlalchemy import select

from flexmeasures import Sensor
from flexmeasures.data import db


def make_sensor_data_request_for_gas_sensor(
    num_values: int = 6,
    duration: str = "PT1H",
    unit: str = "m³",
    include_a_null: bool = False,
    sensor_name: str = "some gas sensor",
) -> dict:
    """Creates request to post sensor data for a gas sensor.
    This particular gas sensor measures units of m³/h with a 10-minute resolution.
    """
    sensor = db.session.execute(
        select(Sensor).filter_by(name=sensor_name)
    ).scalar_one_or_none()
    values = num_values * [-11.28]
    if include_a_null:
        values[0] = None
    message: dict = {
        "type": "PostSensorDataRequest",
        "sensor": f"ea1.2021-01.io.flexmeasures:fm1.{sensor.id}",
        "values": values,
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


def get_sensor_post_data(generic_asset_id: int = 2) -> dict:
    post_data = {
        "name": "power",
        "event_resolution": "PT1H",
        "unit": "kWh",
        "generic_asset_id": generic_asset_id,
        "attributes": '{"capacity_in_mw": 0.0074, "max_soc_in_mwh": 0.04, "min_soc_in_mwh": 0.008}',
    }
    return post_data


def message_for_trigger_schedule(
    unknown_prices: bool = False,
    with_targets: bool = False,
    realistic_targets: bool = True,
    too_far_into_the_future_targets: bool = False,
    use_time_window: bool = False,
) -> dict:
    message = {
        "start": "2015-01-01T00:00:00+01:00",
        "duration": "PT24H",  # Will be extended in case of targets that would otherwise lie beyond the schedule's end
    }
    if unknown_prices:
        message[
            "start"
        ] = "2040-01-01T00:00:00+01:00"  # We have no beliefs in our test database about 2040 prices

    message["flex-model"] = {
        "soc-at-start": 12.1,  # in kWh, according to soc-unit
        "soc-min": 0,  # in kWh, according to soc-unit
        "soc-max": 40,  # in kWh, according to soc-unit
        "soc-unit": "kWh",
        "roundtrip-efficiency": "98%",
        "storage-efficiency": "99.99%",
        "power-capacity": "2 MW",  # same as capacity_in_mw attribute of test battery and test charging station
    }
    if with_targets:
        if realistic_targets:
            # this target (in kWh, according to soc-unit) is well below the soc_max_in_mwh on the battery's sensor attributes
            target_value = 25
        else:
            # this target (in kWh, according to soc-unit) is actually higher than soc_max_in_mwh on the battery's sensor attributes
            target_value = 25000
        if too_far_into_the_future_targets:
            # this target exceeds FlexMeasures' default max planning horizon
            target_datetime = "2015-02-02T23:00:00+01:00"
        else:
            target_datetime = "2015-01-02T23:00:00+01:00"
        if use_time_window:
            target_time_window = {
                "start": "2015-01-02T22:45:00+01:00",
                "end": target_datetime,
            }
        else:
            target_time_window = {"datetime": target_datetime}
        message["flex-model"]["soc-targets"] = [
            {"value": target_value, **target_time_window}
        ]
        # Also create some minima and maxima constraints to test correct deserialization using the soc-unit
        message["flex-model"]["soc-minima"] = [
            {"value": target_value - 1, **target_time_window}
        ]
        message["flex-model"]["soc-maxima"] = [
            {"value": target_value + 1, **target_time_window}
        ]
    return message
