"""
Utils for FlexMeasures CLI
"""

from __future__ import annotations

from typing import Any
from datetime import datetime, timedelta

import click
from tabulate import tabulate
import pytz
from click_default_group import DefaultGroup

from flexmeasures.utils.time_utils import get_most_recent_hour, get_timezone
from flexmeasures.utils.validation_utils import validate_color_hex, validate_url
from flexmeasures import Sensor


class MsgStyle(object):
    """Stores the text styles for the different events

    Styles options are the attributes of the `click.style` which can be found
    [here](https://click.palletsprojects.com/en/8.1.x/api/#click.style).

    """

    SUCCESS: dict[str, Any] = {"fg": "green"}
    WARN: dict[str, Any] = {"fg": "yellow"}
    ERROR: dict[str, Any] = {"fg": "red"}


class DeprecatedOption(click.Option):
    """A custom option that can be used to mark an option as deprecated.

    References
    ----------------

    Copied from  https://stackoverflow.com/a/50402799/13775459
    """

    def __init__(self, *args, **kwargs):
        self.deprecated = kwargs.pop("deprecated", ())
        self.preferred = kwargs.pop("preferred", args[0][-1])
        super(DeprecatedOption, self).__init__(*args, **kwargs)


class DeprecatedOptionsCommand(click.Command):
    """A custom command that can be used to mark options as deprecated.

    References
    ----------------

    Adapted from  https://stackoverflow.com/a/50402799/13775459
    """

    def make_parser(self, ctx):
        """Hook 'make_parser' and during processing check the name
        used to invoke the option to see if it is preferred"""

        parser = super(DeprecatedOptionsCommand, self).make_parser(ctx)

        # get the parser options
        options = set(parser._short_opt.values())
        options |= set(parser._long_opt.values())

        for option in options:
            if not isinstance(option.obj, DeprecatedOption):
                continue

            def make_process(an_option):
                """Construct a closure to the parser option processor"""

                orig_process = an_option.process
                deprecated = getattr(an_option.obj, "deprecated", None)
                preferred = getattr(an_option.obj, "preferred", None)
                msg = "Expected `deprecated` value for `{}`"
                assert deprecated is not None, msg.format(an_option.obj.name)

                def process(value, state):
                    """The function above us on the stack used 'opt' to
                    pick option from a dict, see if it is deprecated"""

                    # reach up the stack and get 'opt'
                    import inspect

                    frame = inspect.currentframe()
                    try:
                        opt = frame.f_back.f_locals.get("opt")
                    finally:
                        del frame

                    if opt in deprecated:
                        click.secho(
                            f"Option '{opt}' will be replaced by '{preferred}'.",
                            **MsgStyle.WARN,
                        )
                    return orig_process(value, state)

                return process

            option.process = make_process(option)

        return parser


class DeprecatedDefaultGroup(DefaultGroup):
    """Invokes a default subcommand, *and* shows a deprecation message.

    Also adds the `invoked_default` boolean attribute to the context.
    A group callback can use this information to figure out if it's being executed directly
    (invoking the default subcommand) or because the execution flow passes onwards to a subcommand.
    By default it's None, but it can be the name of the default subcommand to execute.

    .. sourcecode:: python

        import click
        from flexmeasures.cli.utils import DeprecatedDefaultGroup

        @click.group(cls=DeprecatedDefaultGroup, default="bar", deprecation_message="renamed to `foo bar`.")
        def foo(ctx):
            if ctx.invoked_default:
                click.echo("foo")

        @foo.command()
        def bar():
            click.echo("bar")

    .. sourcecode:: console

        $ flexmeasures foo
        DeprecationWarning: renamed to `foo bar`.
        foo
        bar
        $ flexmeasures foo bar
        bar
    """

    def __init__(self, *args, **kwargs):
        self.deprecation_message = "DeprecationWarning: " + kwargs.pop(
            "deprecation_message", ""
        )
        super().__init__(*args, **kwargs)

    def get_command(self, ctx, cmd_name):
        ctx.invoked_default = None
        if cmd_name not in self.commands:
            click.echo(click.style(self.deprecation_message, fg="red"), err=True)
            ctx.invoked_default = self.default_cmd_name
        return super().get_command(ctx, cmd_name)


def get_timerange_from_flag(
    last_hour: bool = False,
    last_day: bool = False,
    last_7_days: bool = False,
    last_month: bool = False,
    last_year: bool = False,
    timezone: pytz.BaseTzInfo | None = None,
) -> tuple[datetime, datetime]:
    """This function returns a time range [start,end] of the last-X period.
    See input parameters for more details.

    :param bool last_hour: flag to get the time range of the last finished hour.
    :param bool last_day: flag to get the time range for yesterday.
    :param bool last_7_days: flag to get the time range of the previous 7 days.
    :param bool last_month: flag to get the time range of last calendar month
    :param bool last_year: flag to get the last completed calendar year
    :param timezone: timezone object to represent
    :returns: start:datetime, end:datetime
    """

    if timezone is None:
        timezone = get_timezone()

    current_hour = get_most_recent_hour().astimezone(timezone)

    if last_hour:  # last finished hour
        end = current_hour
        start = current_hour - timedelta(hours=1)

    if last_day:  # yesterday
        end = current_hour.replace(hour=0)
        start = end - timedelta(days=1)

    if last_7_days:  # last finished 7 day period.
        end = current_hour.replace(hour=0)
        start = end - timedelta(days=7)

    if last_month:
        end = current_hour.replace(
            hour=0, day=1
        )  # get the first day of the current month
        start = (end - timedelta(days=1)).replace(
            day=1
        )  # get first day of the previous month

    if last_year:  # last calendar year
        end = current_hour.replace(
            month=1, day=1, hour=0
        )  # get first day of current year
        start = (end - timedelta(days=1)).replace(
            day=1, month=1
        )  # get first day of previous year

    return start, end


def validate_unique(ctx, param, value):
    """Callback function to ensure multiple values are unique."""
    if value is not None:
        # Check if all values are unique
        if len(value) != len(set(value)):
            raise click.BadParameter("Values must be unique.")
    return value


def abort(message: str):
    click.secho(message, **MsgStyle.ERROR)
    raise click.Abort()


def done(message: str):
    click.secho(message, **MsgStyle.SUCCESS)


def path_to_str(path: list, separator: str = ">") -> str:
    """
    Converts a list representing a path to a string format, using a specified separator.
    """

    return separator.join(path)


def are_all_equal(paths: list[list[str]]) -> bool:
    """
    Checks if all given entity paths represent the same path.
    """
    return len(set(path_to_str(p) for p in paths)) == 1


def reduce_entity_paths(asset_paths: list[list[str]]) -> list[list[str]]:
    """
    Simplifies a list of entity paths by trimming their common ancestor.

    Examples:
    >>> reduce_entity_paths([["Account1", "Asset1"], ["Account2", "Asset2"]])
    [["Account1", "Asset1"], ["Account2", "Asset2"]]

    >>> reduce_entity_paths([["Asset1"], ["Asset2"]])
    [["Asset1"], ["Asset2"]]

    >>> reduce_entity_paths([["Account1", "Asset1"], ["Account1", "Asset2"]])
    [["Asset1"], ["Asset2"]]

    >>> reduce_entity_paths([["Asset1", "Asset2"], ["Asset1"]])
    [["Asset1"], ["Asset1", "Asset2"]]

    >>> reduce_entity_paths([["Account1", "Asset", "Asset1"], ["Account1", "Asset", "Asset2"]])
    [["Asset1"], ["Asset2"]]
    """
    reduced_entities = 0

    # At least we need to leave one entity in each list
    max_reduced_entities = min([len(p) - 1 for p in asset_paths])

    # Find the common path
    while (
        are_all_equal([p[:reduced_entities] for p in asset_paths])
        and reduced_entities <= max_reduced_entities
    ):
        reduced_entities += 1

    return [p[reduced_entities - 1 :] for p in asset_paths]


def get_sensor_aliases(
    sensors: list[Sensor],
    reduce_paths: bool = True,
    separator: str = "/",
) -> dict:
    """
    Generates aliases for all sensors by appending a unique path to each sensor's name.

    Parameters:
    :param sensors:         A list of Sensor objects.
    :param reduce_paths:    Flag indicating whether to reduce each sensor's entity path. Defaults to True.
    :param separator:       Character or string used to separate entities within each sensor's path. Defaults to "/".

    :return: A dictionary mapping sensor IDs to their generated aliases.
    """

    entity_paths = [
        s.generic_asset.get_path(separator=separator).split(separator) for s in sensors
    ]
    if reduce_paths:
        entity_paths = reduce_entity_paths(entity_paths)
    entity_paths = [path_to_str(p, separator=separator) for p in entity_paths]

    aliases = {
        sensor.id: f"{sensor.name} ({path})"
        for path, sensor in zip(entity_paths, sensors)
    }

    return aliases


def validate_color_cli(ctx, param, value):
    """
    Optional parameter validation

    Validates that a given value is a valid hex color code.

    Parameters:
    :param ctx:     Click context.
    :param param:   Click parameter name.
    :param value:   The color code to validate.
    """

    try:
        validate_color_hex(value)
    except ValueError as e:
        click.secho(str(e), **MsgStyle.ERROR)
        raise click.Abort()


def validate_url_cli(ctx, param, value):
    """
    Optional parameter validation

    Validates that a given value is a valid URL format using regex.

    Parameters:
    :param ctx:     Click context.
    :param param:   Click parameter name.
    :param value:   The URL to validate.
    """

    try:
        validate_url(value)
    except ValueError as e:
        click.secho(str(e), **MsgStyle.ERROR)
        raise click.Abort()


def tabulate_account_assets(assets):
    """
    Print a tabulated representation of the given assets.

    Args:
        assets: an iterable of GenericAsset objects

    """
    asset_data = [
        (
            asset.id,
            asset.name,
            asset.generic_asset_type.name,
            asset.parent_asset_id,
            asset.location,
        )
        for asset in assets
    ]
    click.echo(
        tabulate(asset_data, headers=["ID", "Name", "Type", "Parent ID", "Location"])
    )

import os
import pandas as pd
from datetime import datetime, timedelta
from dateutil.parser import isoparse
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.utils.time_utils import server_now
import click


def floor_to_resolution(dt: datetime, resolution: timedelta) -> datetime:
    delta_seconds = resolution.total_seconds()
    floored = dt.timestamp() - (dt.timestamp() % delta_seconds)
    return datetime.fromtimestamp(floored, tz=dt.tzinfo)


def resolve_forecast_config(
    sensors: dict,
    regressors: list[str],
    future_regressors: list[str],
    target: str,
    start_date: datetime,
    end_date: datetime,
    train_period: int | None,
    start_predict_date: str | None,
    predict_period: int | None,
    sensor_to_save: int | None,
    model_save_dir: str,
    output_path: str | None,
    max_forecast_horizon: int,
    forecast_frequency: int,
    probabilistic: bool,
) -> dict:
    """
    Validate and resolve forecasting parameters.

    Returns:
        dict of resolved arguments for TrainPredictPipeline
    Raises:
        click.BadParameter on invalid inputs
    """

    if not (regressors or future_regressors):
        regressors = ["autoregressive"]

    # Auto-fill regressors if empty and future_regressors is provided
    if not regressors and future_regressors:
        regressors = future_regressors.copy()

    # Validate sensor keys
    if "autoregressive" not in regressors:
        for key in regressors + [target]:
            if key not in sensors:
                raise click.BadParameter(f"Sensor '{key}' not found in --sensors")

    # Validate future regressors are subset of regressors
    missing = set(future_regressors) - set(regressors)
    if missing:
        raise click.BadParameter(
            f"--future-regressors contains entries not found in --regressors: {missing}"
        )

    if start_date >= end_date:
        raise click.BadParameter("--start-date must be before --end-date")

    regressors_list = regressors
    future_regressors_list = future_regressors

    target_sensor = Sensor.query.get(sensors[target])
    if not target_sensor:
        raise click.BadParameter(f"Target sensor '{target}' not found in DB.")

    resolution = target_sensor.event_resolution

    if start_predict_date is None:
        predict_start = floor_to_resolution(server_now(), resolution)
    else:
        predict_start = isoparse(start_predict_date)

    if predict_start < start_date:
        raise click.BadParameter("--start-predict-date cannot be before --start-date")
    if predict_start >= end_date:
        raise click.BadParameter("--start-predict-date must be before --end-date")

    if train_period is None:
        train_period_in_hours = int((predict_start - start_date).total_seconds() / 3600)
        if train_period_in_hours < 48:
            raise click.BadParameter("--train-period must be at least 2 days (48 hours). consider reducing --start-date. or increasing --start-predict-date.")
    else:
        train_period_in_hours = int(train_period) * 24
        if train_period_in_hours < 48:
            raise click.BadParameter("--train-period must be at least 2 days (48 hours). consider increasing --train-period.")

    if predict_period is None:
        predict_period_in_hours = int((end_date - predict_start).total_seconds() / 3600)
    else:
        predict_period_in_hours = int(predict_period)
        if predict_period_in_hours < 1:
            raise click.BadParameter("--predict-period must be at least 1 hour")

    if predict_period_in_hours <= 0:
        raise click.BadParameter("--predict-period must be greater than 0")

    if "autoregressive" in regressors_list:
        sensors = {target: sensors[target]}  # reduce to AR

    if max_forecast_horizon is None and forecast_frequency is None:
        max_forecast_horizon = predict_period_in_hours
        forecast_frequency = predict_period_in_hours
    elif max_forecast_horizon is None:
        max_forecast_horizon = predict_period_in_hours
    elif forecast_frequency is None:
        forecast_frequency = max_forecast_horizon

    if sensor_to_save is None:
        sensor_to_save = target_sensor

    # Ensure output path exists if provided
    if output_path and not os.path.exists(output_path):
        os.makedirs(output_path)

    return dict(
        sensors=sensors,
        regressors=regressors_list,
        future_regressors=future_regressors_list,
        target=target,
        model_save_dir=model_save_dir,
        output_path=output_path,
        start_date=start_date,
        end_date=end_date,
        train_period_in_hours=train_period_in_hours,
        predict_start=predict_start,
        predict_period_in_hours=predict_period_in_hours,
        max_forecast_horizon=max_forecast_horizon,
        forecast_frequency=forecast_frequency,
        probabilistic=probabilistic,
        sensor_to_save=sensor_to_save,
    )
