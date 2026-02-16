import click
import marshmallow as ma
import pandas as pd
from datetime import datetime
from click import get_current_context
from flask.cli import with_appcontext as with_cli_appcontext
from pint import DefinitionSyntaxError, DimensionalityError, UndefinedUnitError

from flexmeasures.utils.unit_utils import to_preferred, ur, extract_unit_from_string
from flexmeasures.data.models.time_series import Sensor


class MarshmallowClickMixin(click.ParamType):
    def __init__(self, *args, **kwargs):

        metadata_keys = ["description", "example"]
        metadata = dict(kwargs.get("metadata", {}))
        for key in metadata_keys:
            value = kwargs.pop(key, None)
            if value is not None:
                metadata[key] = value
        if metadata:
            kwargs["metadata"] = metadata

        super().__init__(*args, **kwargs)
        self.name = self.__class__.__name__

    def get_metavar(self, param, **kwargs):
        return self.__class__.__name__

    def convert(self, value, param, ctx, **kwargs):
        try:
            return self.deserialize(value, **kwargs)
        except ma.exceptions.ValidationError as e:
            raise click.exceptions.BadParameter(e, ctx=ctx, param=param)


class FMValidationError(ma.exceptions.ValidationError):
    """
    Custom validation error class.
    It differs from the classic validation error by having two
    attributes, according to the USEF 2015 reference implementation.
    Subclasses of this error might adjust the `status` attribute accordingly.
    """

    result = "Rejected"
    status = "UNPROCESSABLE_ENTITY"


def with_appcontext_if_needed():
    """Execute within the script's application context, in case there is one.

    An exception is `flexmeasures run`, which has a click context at the time the decorator is called,
    but no longer has a click context at the time the decorated function is called,
    which, typically, is a request to the running FlexMeasures server.
    """

    def decorator(f):
        ctx = get_current_context(silent=True)
        if ctx and not ctx.invoked_subcommand == "run":
            return with_cli_appcontext(f)
        return f

    return decorator


def convert_to_quantity(value: str, to_unit: str) -> ur.Quantity:
    """Convert value to quantity in the given unit.

    :param value:       Value to convert.
    :param to_unit:     Unit to convert to. If the unit starts with a '/',
                        the value can have any unit, and the unit is used as the denominator.
    :returns:           Quantity in the desired unit.
    """
    if to_unit.startswith("/") and len(to_unit) < 2:
        raise ValueError(f"Variable `to_unit='{to_unit}'` must define a denominator.")
    try:
        if to_unit.startswith("/"):
            return to_preferred(
                ur.Quantity(value) * ur.Quantity(to_unit[1:])
            ) / ur.Quantity(to_unit[1:])
        return ur.Quantity(value).to(ur.Quantity(to_unit))
    except DimensionalityError as e:
        raise FMValidationError(f"Cannot convert value `{value}` to '{to_unit}'") from e
    except (AssertionError, DefinitionSyntaxError, UndefinedUnitError) as e:
        raise FMValidationError(
            f"Cannot convert value '{value}' to a valid quantity. {e}"
        )


def extract_sensors_from_flex_config(plot: dict) -> tuple[list[Sensor], list[dict]]:
    """
    Extracts a consolidated list of sensors from an asset based on
    flex-context or flex-model definitions provided in a plot dictionary.
    """
    all_sensors = []
    asset_refs = []

    from flexmeasures.data.schemas.generic_assets import (
        GenericAssetIdField,
    )  # Import here to avoid circular imports

    asset = GenericAssetIdField().deserialize(plot.get("asset"))

    if asset is None:
        raise FMValidationError("Asset not found for the provided plot configuration.")

    fields_to_check = {
        "flex-context": asset.flex_context,
        "flex-model": asset.flex_model,
    }

    for plot_key, flex_config in fields_to_check.items():
        if plot_key in plot:
            field_key = plot[plot_key]
            data = flex_config or {}
            field_value = data.get(field_key)

            if isinstance(field_value, dict):
                # Add a single sensor if it exists
                sensor = field_value.get("sensor")
                if sensor:
                    all_sensors.append(sensor)
            elif isinstance(field_value, str):
                unit = None
                # extract unit from the string value and add a dummy sensor with that unit
                value, unit = extract_unit_from_string(field_value)
                if unit is not None:
                    asset_refs.append(
                        {
                            "id": asset.id,
                            "field": field_key,
                            "value": value,
                            "unit": unit,
                        }
                    )
                else:
                    raise FMValidationError(
                        f"Value '{field_value}' for field '{field_key}' in '{plot_key}' is not a valid quantity string."
                    )

    return all_sensors, asset_refs


def generate_constant_time_series(
    event_start: str,
    event_end: str,
    value: float,
    sid: int,
    src: int = 1,
    belief_time: datetime = None,
) -> list[dict]:
    """
    Generates a list of data points with a 1-hour frequency.

    :param event_start: Start of the range
    :param event_end: End of the range
    :param value: The constant value for 'val'
    :param sid: Sensor ID
    :param src: Source ID
    :param belief_time: The time the data was "generated".
                       If None, it defaults to the start of the events.
    """
    if belief_time is None:
        belief_time = event_start

    # Create hourly range
    # We use inclusive='left' to ensure we don't exceed the end date
    # if the end date represents the boundary of the last interval.
    dr = pd.date_range(start=event_start, end=event_end, freq="1h", inclusive="left")

    data = []

    # Convert belief_time to milliseconds for the 'bh' calculation
    bt_ms = int(belief_time.timestamp() * 1000)

    for ts in dr:
        ts_ms = int(ts.timestamp() * 1000)

        # In your data: ts - bh = bt => bh = ts - bt
        belief_horizon = ts_ms - bt_ms

        data.append(
            {
                "ts": ts_ms,
                "sid": sid,
                "val": float(value),
                "sf": 1.0,
                "src": src,
                "bh": belief_horizon,
            }
        )

    return data
