from __future__ import annotations

from packaging import version
from datetime import date, datetime, timedelta

from flask import current_app
import pandas as pd
from pandas.tseries.frequencies import to_offset
import numpy as np
import timely_beliefs as tb

from flexmeasures.data.models.planning.exceptions import UnknownPricesException
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures import Asset
from flexmeasures.data.models.planning import StockCommitment
from flexmeasures.data.queries.utils import simplify_index

from flexmeasures.utils.flexmeasures_inflection import capitalize, pluralize
from flexmeasures.utils.unit_utils import ur, convert_units
from pint.errors import UndefinedUnitError, DimensionalityError


def initialize_df(
    columns: list[str],
    start: datetime,
    end: datetime,
    resolution: timedelta,
    inclusive: str = "left",
) -> pd.DataFrame:
    df = pd.DataFrame(
        index=initialize_index(start, end, resolution, inclusive), columns=columns
    )
    return df


def initialize_series(
    data: pd.Series | list[float] | np.ndarray | float | None,
    start: datetime,
    end: datetime,
    resolution: timedelta,
    inclusive: str = "left",
) -> pd.Series:
    s = pd.Series(index=initialize_index(start, end, resolution, inclusive), data=data)
    return s


def initialize_index(
    start: date | datetime | str,
    end: date | datetime | str,
    resolution: timedelta | str,
    inclusive: str = "left",
) -> pd.DatetimeIndex:
    if version.parse(pd.__version__) >= version.parse("1.4.0"):
        return pd.date_range(
            start=start,
            end=end,
            freq=to_offset(resolution),
            inclusive=inclusive,
            name="datetime",
        )
    else:
        return pd.date_range(
            start=start,
            end=end,
            freq=to_offset(resolution),
            closed=inclusive,
            name="datetime",
        )


def add_tiny_price_slope(
    orig_prices: pd.DataFrame, col_name: str = "event_value", d: float = 10**-4
) -> pd.DataFrame:
    """Add tiny price slope to col_name to represent e.g. inflation as a simple linear price increase.
    This is meant to break ties, when multiple time slots have equal prices, in favour of acting sooner.
    We penalise the future with at most d times the price spread (1 per thousand by default).
    """
    prices = orig_prices.copy()
    price_spread = prices[col_name].max() - prices[col_name].min()
    if price_spread > 0:
        max_penalty = price_spread * d
    else:
        max_penalty = d
    prices[col_name] = prices[col_name] + np.linspace(
        0, max_penalty, prices[col_name].size
    )
    return prices


def ensure_prices_are_not_empty(
    prices: pd.DataFrame,
    price_variable_quantity: Sensor | list[dict] | ur.Quantity | None,
):
    if prices.isnull().values.all() or prices.empty:
        error_message = "Prices unknown for planning window."
        if isinstance(price_variable_quantity, Sensor):
            error_message += f" (sensor {price_variable_quantity.id})"
        raise UnknownPricesException(error_message)


def extend_to_edges(
    df: pd.DataFrame | pd.Series,
    query_window: tuple[datetime, datetime],
    resolution: timedelta,
    kind_of_values: str = "price",
    sensor: Sensor = None,
    allow_trimmed_query_window: bool = False,
):
    """Values are extended to the edges of the query window.

    - The first available value serves as a naive backcasts.
    - The last available value serves as a naive forecast.
    """

    nan_values = df.isnull().values
    if (
        nan_values.any()
        or pd.Timestamp(df.index[0]).tz_convert("UTC")
        != pd.Timestamp(query_window[0]).tz_convert("UTC")
        or pd.Timestamp(df.index[-1]).tz_convert("UTC") + resolution
        != pd.Timestamp(query_window[-1]).tz_convert("UTC")
    ):
        if allow_trimmed_query_window:
            first_event_start = df.first_valid_index()
            last_event_end = df.last_valid_index() + resolution
            sensor_info = (
                f" (sensor {sensor.id})" if sensor and hasattr(sensor, "id") else ""
            )

            current_app.logger.warning(
                f"Prices partially unknown for planning window ({sensor_info}). "
                f"Trimming planning window (from {query_window[0]} until {query_window[-1]}) to {first_event_start} until {last_event_end}."
            )
        else:
            sensor_info = (
                f" (sensor {df.sensor.id})"
                if hasattr(df, "sensor") and hasattr(df.sensor, "id")
                else ""
            )
            current_app.logger.warning(
                f"{capitalize(pluralize(kind_of_values))} partially unknown for planning window ({sensor_info}). "
                f"Assuming the first {kind_of_values} is valid from the start of the planning window ({query_window[0]}), "
                f"and the last {kind_of_values} is valid until the end of the planning window ({query_window[-1]})."
            )
            index = initialize_index(
                start=query_window[0],
                end=query_window[1],
                resolution=resolution,
            )
            df = df.reindex(index)
            # or to also forward fill intermediate NaN values, use: df = df.ffill().bfill()
            df[: df.first_valid_index()] = df[
                df.index == df.first_valid_index()
            ].values[0]
            df[df.last_valid_index() :] = df[df.index == df.last_valid_index()].values[
                0
            ]
    return df


def get_power_values(
    query_window: tuple[datetime, datetime],
    resolution: timedelta,
    beliefs_before: datetime | None,
    sensor: Sensor,
) -> np.ndarray:
    """Get measurements or forecasts of an inflexible device represented by a power or energy sensor as an array of power values in MW.

    If the requested schedule lies in the future, the returned data will consist of (the most recent) forecasts (if any exist).
    If the requested schedule lies in the past, the returned data will consist of (the most recent) measurements (if any exist).
    The latter amounts to answering "What if we could have scheduled under perfect foresight?".

    :param query_window:    datetime window within which events occur (equal to the scheduling window)
    :param resolution:      timedelta used to resample the forecasts to the resolution of the schedule
    :param beliefs_before:  datetime used to indicate we are interested in the state of knowledge at that time
    :param sensor:          power sensor representing an energy flow out of the device
    :returns:               power measurements or forecasts (consumption is positive, production is negative)
    """
    bdf: tb.BeliefsDataFrame = TimedBelief.search(
        sensor,
        event_starts_after=query_window[0],
        event_ends_before=query_window[1],
        resolution=to_offset(resolution).freqstr,
        beliefs_before=beliefs_before,
        most_recent_beliefs_only=True,
        one_deterministic_belief_per_event=True,
    )  # consumption is negative, production is positive
    df = simplify_index(bdf)
    df = df.reindex(initialize_index(query_window[0], query_window[1], resolution))
    nan_values = df.isnull().values
    if nan_values.any() or df.empty:
        current_app.logger.warning(
            f"Assuming zero power values for (partially) unknown power values for planning window. (sensor {sensor.id})"
        )
        df = df.astype(float).fillna(0)

    series = convert_units(df.values, sensor.unit, "MW")

    if sensor.get_attribute(
        "consumption_is_positive", False
    ):  # FlexMeasures default is to store consumption as negative power values
        return series

    return -series


def fallback_charging_policy(
    sensor: Sensor,
    device_constraints: pd.DataFrame,
    start: datetime,
    end: datetime,
    resolution: timedelta,
) -> pd.Series:
    """This fallback charging policy is to just start charging or discharging, or do neither,
    depending on the first target state of charge and the capabilities of the Charge Point.
    Note that this ignores any cause of the infeasibility and,
    while probably a decent policy for Charge Points,
    should not be considered a robust policy for other asset types.
    """
    max_charge_capacity = (
        device_constraints[["derivative max", "derivative equals"]].min().min()
    )
    max_discharge_capacity = (
        -device_constraints[["derivative min", "derivative equals"]].max().max()
    )
    charge_power = max_charge_capacity if sensor.get_attribute("is_consumer") else 0
    discharge_power = (
        -max_discharge_capacity if sensor.get_attribute("is_producer") else 0
    )

    charge_schedule = initialize_series(charge_power, start, end, resolution)
    discharge_schedule = initialize_series(discharge_power, start, end, resolution)
    idle_schedule = initialize_series(0, start, end, resolution)
    if (
        device_constraints["equals"].first_valid_index() is not None
        and device_constraints["equals"][
            device_constraints["equals"].first_valid_index()
        ]
        > 0
    ):
        # start charging to get as close as possible to the next target
        return idle_after_reaching_target(charge_schedule, device_constraints["equals"])
    if (
        device_constraints["equals"].first_valid_index() is not None
        and device_constraints["equals"][
            device_constraints["equals"].first_valid_index()
        ]
        < 0
    ):
        # start discharging to get as close as possible to the next target
        return idle_after_reaching_target(
            discharge_schedule, device_constraints["equals"]
        )
    if (
        device_constraints["max"].first_valid_index() is not None
        and device_constraints["max"][device_constraints["max"].first_valid_index()] < 0
    ):
        # start discharging to try and bring back the soc below the next max constraint
        return idle_after_reaching_target(discharge_schedule, device_constraints["max"])
    if (
        device_constraints["min"].first_valid_index() is not None
        and device_constraints["min"][device_constraints["min"].first_valid_index()] > 0
    ):
        # start charging to try and bring back the soc above the next min constraint
        return idle_after_reaching_target(charge_schedule, device_constraints["min"])
    # stand idle
    return idle_schedule


def idle_after_reaching_target(
    schedule: pd.Series,
    target: pd.Series,
    initial_state: float = 0,
) -> pd.Series:
    """Stop planned (dis)charging after target is reached (or constraint is met)."""
    first_target = target[target.first_valid_index()]
    if first_target > initial_state:
        schedule[schedule.cumsum() > first_target] = 0
    else:
        schedule[schedule.cumsum() < first_target] = 0
    return schedule


def get_quantity_from_attribute(
    entity: Asset | Sensor,
    attribute: str | None,
    unit: str | ur.Quantity,
) -> ur.Quantity:
    """Get the value (in the given unit) of a quantity stored as an entity attribute.

    :param entity:      The entity (sensor or asset) containing the attribute to retrieve the value from.
    :param attribute:   The attribute name to extract the value from.
    :param unit:        The unit in which the value should be returned.
    :return:            The retrieved quantity or the provided default.
    """
    if attribute is None:
        return np.nan * ur.Quantity(unit)  # at least return result in the desired unit

    # Get the default value from the entity attribute
    value: str | float | int = entity.get_attribute(attribute, np.nan)

    # Try to convert it to a quantity in the desired unit
    try:
        q = ur.Quantity(value)
        q = q.to(unit)
    except (UndefinedUnitError, DimensionalityError, ValueError, AssertionError):
        try:
            # Fall back to interpreting the value in the given unit
            q = ur.Quantity(f"{value} {unit}")
            q = q.to(unit)
        except (UndefinedUnitError, DimensionalityError, ValueError, AssertionError):
            current_app.logger.warning(f"Couldn't convert {value} to `{unit}`")
            q = np.nan * ur.Quantity(unit)  # at least return result in the desired unit
    return q


def get_series_from_quantity_or_sensor(
    variable_quantity: Sensor | list[dict] | ur.Quantity,
    unit: ur.Quantity | str,
    query_window: tuple[datetime, datetime],
    resolution: timedelta,
    beliefs_before: datetime | None = None,
    as_instantaneous_events: bool = True,
    resolve_overlaps: str = "first",
    fill_sides: bool = False,
) -> pd.Series:
    """
    Get a time series given a quantity or sensor defined on a time window.

    :param variable_quantity:       Variable quantity measuring e.g. power capacity or efficiency.
                                    One of the following types:
                                    - a timely-beliefs Sensor recording the data
                                    - a list of dictionaries representing a time series specification
                                    - a pint Quantity representing a fixed quantity
    :param unit:                    Unit of the output data.
    :param query_window:            Tuple representing the start and end of the requested data.
    :param resolution:              Time resolution of the requested data.
    :param beliefs_before:          Optional datetime used to indicate we are interested in the state of knowledge
                                    at that time.
    :param as_instantaneous_events: Optionally, convert to instantaneous events, in which case the passed resolution is
                                    interpreted as the desired frequency of the data.
    :param resolve_overlaps:        If time series segments overlap (e.g. when upsampling to instantaneous events),
                                    take the 'max', 'min' or 'first' value during overlapping time spans
                                    (or at instantaneous moments, such as at event boundaries).
    :param fill_sides               If True, values are extended to the edges of the query window:
                                    - The first available value serves as a naive backcast.
                                    - The last available value serves as a naive forecast.
    :return:                        Pandas Series with the requested time series data.
    """

    start, end = query_window
    index = initialize_index(start=start, end=end, resolution=resolution)

    if isinstance(variable_quantity, ur.Quantity):
        if np.isnan(variable_quantity.magnitude):
            magnitude = np.nan
        else:
            magnitude = convert_units(
                variable_quantity.magnitude,
                str(variable_quantity.units),
                unit,
                resolution,
            )
        time_series = pd.Series(magnitude, index=index, name="event_value")
    elif isinstance(variable_quantity, Sensor):
        bdf: tb.BeliefsDataFrame = TimedBelief.search(
            variable_quantity,
            event_starts_after=query_window[0],
            event_ends_before=query_window[1],
            resolution=resolution,
            # frequency=resolution,
            beliefs_before=beliefs_before,
            most_recent_beliefs_only=True,
            one_deterministic_belief_per_event=True,
        )
        if as_instantaneous_events:
            bdf = bdf.resample_events(timedelta(0), boundary_policy=resolve_overlaps)
        time_series = simplify_index(bdf).reindex(index).squeeze()
        time_series = convert_units(
            time_series, variable_quantity.unit, unit, resolution
        )
    elif isinstance(variable_quantity, list):
        time_series = process_time_series_segments(
            index=index,
            variable_quantity=variable_quantity,
            unit=unit,
            resolution=resolution if not as_instantaneous_events else timedelta(0),
            resolve_overlaps=resolve_overlaps,
            fill_sides=fill_sides,
        )
    else:
        raise TypeError(
            f"quantity_or_sensor {variable_quantity} should be a pint Quantity or timely-beliefs Sensor"
        )

    return time_series


def process_time_series_segments(
    index: pd.DatetimeIndex,
    variable_quantity: list[dict],
    unit: str,
    resolution: timedelta,
    resolve_overlaps: str,
    fill_sides: bool = False,
) -> pd.Series:
    """
    Process a time series defined by a list of dicts, while resolving overlapping segments.

    Parameters:
        index:              The index for the time series DataFrame.
        variable_quantity:  List of events, where each event is a dictionary containing:
                            - 'value': The value of the event (can be a Quantity or scalar).
                            - 'start': The start datetime of the event.
                            - 'end': The end datetime of the event.
        unit:               The unit to convert the value into if it's a Quantity.
        resolution:         The resolution to subtract from the 'end' to avoid overlap.
        resolve_overlaps:   How to handle overlaps (e.g., 'first', 'last', 'mean', etc.).
        fill_sides:         Whether to extend values to cover the whole index.

    Returns:                A time series with resolved event values.
    """
    # Initialize a DataFrame to hold the segments
    time_series_segments = pd.DataFrame(
        np.nan, index=index, columns=list(range(len(variable_quantity)))
    )

    # Fill in the DataFrame with event values
    for segment, event in enumerate(variable_quantity):
        value = event["value"]
        if isinstance(value, ur.Quantity):
            # Convert value to the specified unit if it's a Quantity
            if np.isnan(value.magnitude):
                value = np.nan
            else:
                value = convert_units(
                    value.magnitude, str(value.units), unit, resolution
                )
        start = event["start"]
        end = event["end"]
        # Assign the value to the corresponding segment in the DataFrame
        time_series_segments.loc[start : end - resolution, segment] = value

    # Resolve overlaps using the specified method
    if resolve_overlaps == "first":
        # Use backfill to fill NaNs with the first non-NaN value
        time_series = (
            time_series_segments.astype(float).fillna(method="bfill", axis=1).iloc[:, 0]
        )
    else:
        # Use the specified method to resolve overlaps (e.g., mean, max)
        time_series = getattr(time_series_segments, resolve_overlaps)(axis=1)

    if fill_sides:
        time_series = extend_to_edges(
            df=time_series,
            query_window=(index[0], index[-1] + resolution),
            resolution=resolution,
        )

    return time_series.rename("event_value")


def get_continuous_series_sensor_or_quantity(
    variable_quantity: Sensor | list[dict] | ur.Quantity | pd.Series | None,
    actuator: Sensor | Asset,
    unit: ur.Quantity | str,
    query_window: tuple[datetime, datetime],
    resolution: timedelta,
    beliefs_before: datetime | None = None,
    fallback_attribute: str | None = None,
    min_value: float | int = np.nan,
    max_value: float | int | pd.Series = np.nan,
    as_instantaneous_events: bool = False,
    resolve_overlaps: str = "first",
    fill_sides: bool = False,
) -> pd.Series:
    """Creates a time series from a sensor, time series specification, or quantity within a specified window,
    falling back to a given `fallback_attribute` and making sure values stay within the domain [min_value, max_value].

    :param variable_quantity:       A sensor recording the data, a time series specification or a fixed quantity.
    :param actuator:                The actuator from which relevant defaults are retrieved.
    :param unit:                    The desired unit of the data.
    :param query_window:            The time window (start, end) to query the data.
    :param resolution:              The resolution or time interval for the data.
    :param beliefs_before:          Timestamp for prior beliefs or knowledge.
    :param fallback_attribute:      Attribute serving as a fallback default in case no quantity or sensor is given.
    :param min_value:               Minimum value.
    :param max_value:               Maximum value (also replacing NaN values).
    :param as_instantaneous_events: optionally, convert to instantaneous events, in which case the passed resolution is
                                    interpreted as the desired frequency of the data.
    :param resolve_overlaps:        If time series segments overlap (e.g. when upsampling to instantaneous events),
                                    take the 'max', 'min' or 'first' value during overlapping time spans
                                    (or at instantaneous moments, such as at event boundaries).
    :param fill_sides               If True, values are extended to the edges of the query window:
                                    - The first available value serves as a naive backcast.
                                    - The last available value serves as a naive forecast.
    :returns:                       time series data with missing values handled based on the chosen method.
    """
    if isinstance(variable_quantity, pd.Series):
        return variable_quantity
    if variable_quantity is None:
        variable_quantity = get_quantity_from_attribute(
            entity=actuator,
            attribute=fallback_attribute,
            unit=unit,
        )

    time_series = get_series_from_quantity_or_sensor(
        variable_quantity=variable_quantity,
        unit=unit,
        query_window=query_window,
        resolution=resolution,
        beliefs_before=beliefs_before,
        as_instantaneous_events=as_instantaneous_events,
        resolve_overlaps=resolve_overlaps,
        fill_sides=fill_sides,
    )

    # Apply upper limit
    time_series = nanmin_of_series_and_value(time_series, max_value)

    # Apply lower limit
    time_series = time_series.clip(lower=min_value)

    return time_series


def nanmin_of_series_and_value(s: pd.Series, value: float | pd.Series) -> pd.Series:
    """Perform a nanmin between a Series and a float."""
    if isinstance(value, pd.Series):
        # Avoid strange InvalidIndexError on .clip due to different "dtype"
        # pd.testing.assert_index_equal(value.index, s.index)
        # [left]:  datetime64[ns, +0000]
        # [right]: datetime64[ns, UTC]
        value = value.tz_convert("UTC")
    return s.astype(float).fillna(value).clip(upper=value)


def initialize_energy_commitment(
    start: pd.Timestamp,
    end: pd.Timestamp,
    resolution: timedelta,
    market_prices: list[float],
) -> pd.DataFrame:
    """Model energy contract for the site."""
    commitment = initialize_df(
        columns=[
            "quantity",
            "downwards deviation price",
            "upwards deviation price",
            "group",
        ],
        start=start,
        end=end,
        resolution=resolution,
    )
    commitment["quantity"] = 0
    commitment["downwards deviation price"] = market_prices
    commitment["upwards deviation price"] = market_prices
    commitment["group"] = list(range(len(commitment)))
    return commitment


def initialize_device_commitment(
    start: pd.Timestamp,
    end: pd.Timestamp,
    resolution: timedelta,
    device: int,
    target_datetime: str,
    target_value: float,
    soc_at_start: float,
    soc_target_penalty: float,
) -> pd.DataFrame:
    """Model penalties for demand unmet per device."""
    stock_commitment = initialize_df(
        columns=[
            "quantity",
            "downwards deviation price",
            "upwards deviation price",
            "group",
        ],
        start=start,
        end=end,
        resolution=resolution,
    )
    stock_commitment.loc[target_datetime, "quantity"] = target_value - soc_at_start
    stock_commitment["downwards deviation price"] = -soc_target_penalty
    stock_commitment["upwards deviation price"] = soc_target_penalty
    stock_commitment["group"] = list(range(len(stock_commitment)))
    stock_commitment["device"] = device
    stock_commitment["class"] = StockCommitment
    return stock_commitment
