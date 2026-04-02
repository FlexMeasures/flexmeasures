from __future__ import annotations

from datetime import timedelta, datetime

from sqlalchemy import select

from flexmeasures import Asset, User
from flexmeasures.data.models.audit_log import AssetAuditLog


def make_sensor_data_request_for_gas_sensor(
    num_values: int = 6,
    duration: str = "PT1H",
    unit: str = "m³",
    include_a_null: bool = False,
) -> dict:
    """Creates request to post sensor data for a gas sensor.
    This particular gas sensor measures units of m³/h with a 10-minute resolution.
    """
    values = num_values * [-11.28]
    if include_a_null:
        values[0] = None
    message: dict = {
        "type": "PostSensorDataRequest",
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
    use_perfect_efficiencies: bool = False,
    resolution: str | None = None,
) -> dict:
    message = {
        "start": "2015-01-01T00:00:00+01:00",
        "duration": "PT24H",  # Will be extended in case of targets that would otherwise lie beyond the schedule's end
    }
    if resolution:
        # The sensor resolution is 15 minutes, but we can override the scheduling resolution here
        message["resolution"] = resolution
    if unknown_prices:
        # We have no beliefs in our test database about 2040 prices
        message["start"] = "2040-01-01T00:00:00+01:00"

    message["flex-model"] = {
        "soc-at-start": 12.1,  # in kWh, according to soc-unit
        "soc-min": 0,  # in kWh, according to soc-unit
        "soc-max": 40,  # in kWh, according to soc-unit
        "soc-unit": "kWh",
        "roundtrip-efficiency": "98%" if not use_perfect_efficiencies else "100%",
        "storage-efficiency": "99.99%" if not use_perfect_efficiencies else 1,
        "power-capacity": "2 MW",  # same as site-power-capacity of test battery and test charging station
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


def check_audit_log_event(
    db,
    event: str,
    user: User,
    asset: Asset,
):
    """Make sure the event is registered in the audit log."""
    logs = db.session.execute(
        select(AssetAuditLog).filter_by(
            event=event,
            active_user_id=user.id,
            active_user_name=user.username,
            affected_asset_id=asset.id,
        )
    ).scalar()
    assert logs, f"expected audit log event: {event}"


def parse_resolution(resolution_str):
    """
    Parses a resolution string (e.g., '10m', '30min', '1h') into a timedelta object.
    """
    import re

    # Regular expression to capture the number and the unit (m/min/h)
    match = re.match(r"(\d+)\s*(m|min|h)", resolution_str, re.I)
    if not match:
        raise ValueError(
            f"Invalid resolution format: {resolution_str}. Use formats like '10m', '30min', '1h'."
        )

    value = int(match.group(1))
    unit = match.group(2).lower()

    if unit in ("m", "min"):
        return timedelta(minutes=value)
    elif unit == "h":
        return timedelta(hours=value)
    else:
        # This would probably not be reached due to the regex, but just in case
        raise ValueError(f"Unsupported time unit: {unit}")


def generate_csv_content(
    start_time_str: str, interval: timedelta, values: list[float]
) -> str:
    """
    Generates a CSV-formatted string with a specified time resolution.

    Args:
        start_time_str (str): The starting timestamp (e.g., '2021-01-01T00:10:00+00:00').
        resolution_str (str): The interval length (e.g., '10m', '30min', '1h').
        values (list of floats): The values to use.

    Returns:
        str: The generated CSV content.
    """
    # Convert the starting time string to a datetime object
    current_time = datetime.fromisoformat(start_time_str)

    # Build the CSV content
    csv_rows = ["Hour,price"]  # Header row

    for value in values:
        # Format the timestamp back into the required string format
        timestamp_str = current_time.strftime("%Y-%m-%dT%H:%M:%S%z")

        # Add new row to CSV content
        csv_rows.append(f"{timestamp_str},{value}")

        # Increment the time for the next interval
        current_time += interval

    # Join all rows
    return "\n".join(csv_rows)
