"""
CLI commands for populating the database
"""

import click

from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas import SensorIdField


@click.group("copy")
def fm_copy_data():
    """FlexMeasures: Copy data."""


@fm_copy_data.command("sensor")
@click.argument(type=SensorIdField)
def copy_sensor(sensor: Sensor):
    """Copy sensor with all of its data

    Example:
        flexmeasures copy sensor 37103874"""
    # todo: create new sensor with the same attributes as the original
    # todo: call copy_beliefs
    # todo: Inform the user about success/failure
    pass

