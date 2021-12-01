"""
This module is part of our data model migration (see https://github.com/SeitaBV/flexmeasures/projects/9).
It will become obsolete when we deprecate the fm0 scheme for entity addresses.
"""

from typing import Union

from flexmeasures.api.common.responses import (
    deprecated_api_version,
    unrecognized_market,
    ResponseTuple,
)
from flexmeasures.data.models.time_series import Sensor


def get_sensor_by_unique_name(sensor_name: str) -> Union[Sensor, ResponseTuple]:
    """Search a sensor by unique name, returning a ResponseTuple if not found.
    This function should be used only for sensors that correspond to the old Market class.
    """
    # Look for the Sensor object
    sensor = Sensor.query.filter(Sensor.name == sensor_name).all()
    if len(sensor) == 0:
        return unrecognized_market(sensor_name)
    elif len(sensor) > 1:
        return deprecated_api_version(
            f"Multiple sensors were found named {sensor_name}."
        )
    return sensor[0]
