"""
This module is part of our data model migration (see https://github.com/SeitaBV/flexmeasures/projects/9).
It will become obsolete when we deprecate the fm0 scheme for entity addresses.
"""

from typing import List, Optional, Union

from flexmeasures.api.common.responses import (
    deprecated_api_version,
    unrecognized_market,
    ResponseTuple,
)
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.queries.sensors import (
    query_sensor_by_name_and_generic_asset_type_name,
)


def get_sensor_by_unique_name(
    sensor_name: str, generic_asset_type_names: Optional[List[str]] = None
) -> Union[Sensor, ResponseTuple]:
    """Search a sensor by unique name, returning a ResponseTuple if it is not found.

    Optionally specify a list of generic asset type names to filter on.
    This function should be used only for sensors that correspond to the old Market class.
    """
    # Look for the Sensor object
    sensors = query_sensor_by_name_and_generic_asset_type_name(
        sensor_name, generic_asset_type_names
    ).all()
    if len(sensors) == 0:
        return unrecognized_market(sensor_name)
    elif len(sensors) > 1:
        return deprecated_api_version(
            f"Multiple sensors were found named {sensor_name}."
        )
    return sensors[0]
