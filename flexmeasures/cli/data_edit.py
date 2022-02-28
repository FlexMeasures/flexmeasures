from typing import Union

import click
from flask import current_app as app
from flask.cli import with_appcontext

from flexmeasures import Sensor
from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import GenericAsset


@click.group("edit")
def fm_edit_data():
    """FlexMeasures: Edit data."""


@fm_edit_data.command("asset-attribute")
@with_appcontext
@click.option(
    "--asset-id",
    "generic_asset_id",
    required=True,
    help="Add/edit attribute to this asset. Follow up with the asset's ID.",
)
@click.option(
    "--attribute",
    "attribute_key",
    required=True,
    help="Add/edit this attribute. Follow up with the name of the asset attribute.",
)
@click.option(
    "--value",
    "attribute_value",
    required=True,
    help="Set the asset attribute to this float value. Use --type to set a type other than a float. Use 'None' to set a null value.",
)
@click.option(
    "--type",
    "attribute_value_type",
    required=False,
    default="float",
    type=click.Choice(["bool", "str", "int", "float"]),
    help="Parse the asset attribute value as this type.",
)
def edit_asset_attribute(
    generic_asset_id: int,
    attribute_key: str,
    attribute_value: Union[bool, str, int, float, None],
    attribute_value_type: str,
):
    """Edit (or add) an asset attribute."""

    # Parse attribute value
    attribute_value = parse_attribute_value(
        attribute_value=attribute_value,
        attribute_value_type=attribute_value_type,
    )

    # Set attribute
    asset = GenericAsset.query.get(generic_asset_id)
    asset.attributes[attribute_key] = attribute_value
    db.session.add(asset)
    db.session.commit()


@fm_edit_data.command("sensor-attribute")
@with_appcontext
@click.option(
    "--sensor-id",
    "sensor_id",
    required=True,
    help="Add/edit attribute to this sensor. Follow up with the sensor's ID.",
)
@click.option(
    "--attribute",
    "attribute_key",
    required=True,
    help="Add/edit this attribute. Follow up with the name of the sensor attribute.",
)
@click.option(
    "--value",
    "attribute_value",
    required=True,
    help="Set the sensor attribute to this float value. Use --type to set a type other than a float. Use 'None' to set a null value.",
)
@click.option(
    "--type",
    "attribute_value_type",
    required=False,
    default="float",
    type=click.Choice(["bool", "str", "int", "float"]),
    help="Parse the asset attribute value as this type.",
)
def edit_sensor_attribute(
    sensor_id: int,
    attribute_key: str,
    attribute_value: Union[bool, str, int, float, None],
    attribute_value_type: str,
):
    """Edit (or add) a sensor attribute."""

    # Parse attribute value
    attribute_value = parse_attribute_value(
        attribute_value=attribute_value,
        attribute_value_type=attribute_value_type,
    )

    # Set attribute
    sensor = Sensor.query.get(sensor_id)
    sensor.attributes[attribute_key] = attribute_value
    db.session.add(sensor)
    db.session.commit()


app.cli.add_command(fm_edit_data)


def parse_attribute_value(
    attribute_value: str, attribute_value_type: str
) -> Union[float, int, bool, str, None]:
    """Parse attribute value."""
    if attribute_value == "None":
        attribute_value = None
    elif attribute_value_type == "float":
        attribute_value = float(attribute_value)
    elif attribute_value_type == "int":
        attribute_value = int(attribute_value)
    elif attribute_value_type == "bool":
        attribute_value = bool(attribute_value)
    elif attribute_value_type == "str":
        pass
    else:
        raise ValueError(f"Unrecognized --type '{attribute_value_type}'.")
    return attribute_value
