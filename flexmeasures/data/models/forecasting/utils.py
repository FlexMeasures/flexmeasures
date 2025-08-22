from __future__ import annotations

import numpy as np
import pandas as pd
import timely_beliefs as tb
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.services.data_sources import get_or_create_source

from datetime import datetime, timedelta
from sqlalchemy import select

from flexmeasures.data import db
from flexmeasures.data.models.forecasting.exceptions import NotEnoughDataException
from flexmeasures.utils.time_utils import as_server_time


def check_data_availability(
    old_sensor_model,
    old_time_series_data_model,
    forecast_start: datetime,
    forecast_end: datetime,
    query_window: tuple[datetime, datetime],
    horizon: timedelta,
):
    """Check if enough data is available in the database in the first place,
    for training window and lagged variables. Otherwise, suggest new forecast period.
    TODO: we could also check regressor data, if we get regressor specs passed in here.
    TODO: The join is probably not needed, should be removed. The speed impactof join is negligible
    """
    from sqlalchemy import func

    # Use aggregate MIN and MAX queries in the database, matching O(n) approach
    first_q = (
        select(func.min(old_time_series_data_model.event_start))
        .join(old_sensor_model.__class__)
        .filter(old_sensor_model.__class__.id == old_sensor_model.id)
    )
    last_q = (
        select(func.max(old_time_series_data_model.event_start))
        .join(old_sensor_model.__class__)
        .filter(old_sensor_model.__class__.id == old_sensor_model.id)
    )
    first_event_start = db.session.execute(first_q).scalar()
    last_event_start = db.session.execute(last_q).scalar()
    if first_event_start is None or last_event_start is None:
        raise NotEnoughDataException(
            "No data available at all. Forecasting impossible."
        )
    first = as_server_time(first_event_start)
    last = as_server_time(last_event_start)
    if query_window[0] < first:
        suggested_start = forecast_start + (first - query_window[0])
        raise NotEnoughDataException(
            f"Not enough data to forecast {old_sensor_model.name} "
            f"for the forecast window {as_server_time(forecast_start)} to {as_server_time(forecast_end)}. "
            f"I needed to query from {as_server_time(query_window[0])}, "
            f"but the first value available is from {first} to {first + old_sensor_model.event_resolution}. "
            f"Consider setting the start date to {as_server_time(suggested_start)}."
        )
    if query_window[1] - horizon > last + old_sensor_model.event_resolution:
        suggested_end = forecast_end + (last - (query_window[1] - horizon))
        raise NotEnoughDataException(
            f"Not enough data to forecast {old_sensor_model.name} "
            f"for the forecast window {as_server_time(forecast_start)} to {as_server_time(forecast_end)}. "
            f"I needed to query until {as_server_time(query_window[1] - horizon)}, "
            f"but the last value available is from {last} to {last + old_sensor_model.event_resolution}. "
            f"Consider setting the end date to {as_server_time(suggested_end)}."
        )


def create_lags(
    n_lags: int,
    sensor: Sensor,
    horizon: timedelta,
    resolution: timedelta,
    use_periodicity: bool,
) -> list[timedelta]:
    """List the lags for this asset type, using horizon and resolution information."""
    lags = []

    # Include a zero lag in case of backwards forecasting
    # Todo: we should always take into account the latest forecast, so always append the zero lag if that belief exists
    if horizon < timedelta(hours=0):
        lags.append(timedelta(hours=0))

    # Include latest measurements
    lag_period = resolution
    number_of_nan_lags = 1 + (horizon - resolution) // lag_period
    for L in range(n_lags):
        lags.append((L + number_of_nan_lags) * lag_period)

    # Include relevant measurements given the asset's periodicity
    if use_periodicity and sensor.get_attribute("daily_seasonality"):
        lag_period = timedelta(days=1)
        number_of_nan_lags = 1 + (horizon - resolution) // lag_period
        for L in range(n_lags):
            lags.append((L + number_of_nan_lags) * lag_period)

    # Remove possible double entries
    return list(set(lags))


def get_query_window(
    training_start: datetime, forecast_end: datetime, lags: list[timedelta]
) -> tuple[datetime, datetime]:
    """Derive query window from start and end date, as well as lags (if any).
    This makes sure we have enough data for lagging and forecasting."""
    if not lags:
        query_start = training_start
    else:
        query_start = training_start - max(lags)
    query_end = forecast_end
    return query_start, query_end


def set_training_and_testing_dates(
    forecast_start: datetime,
    training_and_testing_period: timedelta | tuple[datetime, datetime],
) -> tuple[datetime, datetime]:
    """If needed (if training_and_testing_period is a timedelta),
    derive training_start and testing_end from forecasting_start,
    otherwise simply return training_and_testing_period.


        |------forecast_horizon/belief_horizon------|
        |                  |-------resolution-------|
        belief_time        event_start      event_end


                           |--resolution--|--resolution--|--resolution--|--resolution--|--resolution--|--resolution--|
        |---------forecast_horizon--------|              |              |              |              |              |
        belief_time        event_start    |              |              |              |              |              |
                       |---------forecast_horizon--------|              |              |              |              |
                       belief_time        event_start    |              |              |              |              |
                           |          |---------forecast_horizon--------|              |              |              |
                           |          belief_time        event_start    |              |              |              |
    |--------max_lag-------|--------training_and_testing_period---------|---------------forecast_period--------------|
    query_start            training_start |              |    testing_end/forecast_start              |   forecast_end
        |------min_lag-----|              |          |---------forecast_horizon--------|              |              |
                           |              |          belief_time        event_start    |              |              |
                           |              |              |          |---------forecast_horizon--------|              |
                           |              |              |          belief_time        event_start    |              |
                           |              |              |              |          |---------forecast_horizon--------|
                           |              |              |              |          belief_time        event_start    |
    |--------------------------------------------------query_window--------------------------------------------------|

    """
    if isinstance(training_and_testing_period, timedelta):
        return forecast_start - training_and_testing_period, forecast_start
    else:
        return training_and_testing_period


def negative_to_zero(x: np.ndarray) -> np.ndarray:
    return np.where(x < 0, 0, x)


def data_to_bdf(
    data: pd.DataFrame,
    horizon: int,
    probabilistic: bool,
    sensors: dict[str, int],
    target_sensor: str,
    regressors: list[str],
    sensor_to_save: Sensor,
) -> tb.BeliefsDataFrame:
    """
    Converts a prediction DataFrame into a BeliefsDataFrame for saving to the database.
    Parameters:
    ----------
    data : pd.DataFrame
        DataFrame containing predictions for different forecast horizons.
        If probabilistic forecasts are generated, `data` includes a
        `component` column that encodes which quantile (cumulative probability)
        the row corresponds to.
    horizon : int
        Maximum forecast horizon in time-steps relative to the sensor's resolution. For example, if the sensor resolution is 1 hour, a horizon of 48 represents a forecast horizon of 48 hours. Similarly, if the sensor resolution is 15 minutes, a horizon of 4*48 represents a forecast horizon of 48 hours.
    probabilistic : bool
        Whether the forecasts are probabilistic or deterministic.
    sensors : dict[str, int]
        Dictionary mapping sensor names to sensor IDs.
    target_sensor : str
        The name of the target sensor.
    regressors : list[str]
        List of regressor names.
    sensor_to_save : Sensor
        The sensor object to save the forecasts to.
    Returns:
    -------
    tb.BeliefsDataFrame
        A formatted BeliefsDataFrame ready for database insertion.
    """
    sensor = Sensor.query.get(sensors[target_sensor])
    df = data.copy()
    df.reset_index(inplace=True)
    df.pop("component")

    # Rename target to '0h'
    df = df.rename(columns={target_sensor: "0h"})
    df["event_start"] = pd.to_datetime(df["event_start"])
    df["belief_time"] = pd.to_datetime(df["belief_time"])

    # Probabilities
    probabilistic_values = (
        [float(x.rsplit("_", 1)[-1]) for x in data.index.get_level_values("component")]
        if probabilistic
        else [0.5] * len(df)
    )

    # Build horizons
    horizons = pd.Series(range(1, horizon + 1), name="h")
    expanded = pd.concat([df.assign(h=h) for h in horizons], ignore_index=True)

    # Add shifted event_starts
    expanded["event_start"] = expanded["event_start"] + expanded["h"].apply(
        lambda h: sensor.event_resolution * h
    )

    # Forecast values
    expanded["forecasts"] = expanded.apply(lambda r: r[f"{r.h}h"], axis=1)

    # Probabilities (repeat original values across horizons)
    expanded["cumulative_probability"] = np.repeat(probabilistic_values, horizon)

    # Cleanup
    test_df = expanded[["event_start", "belief_time", "forecasts", "cumulative_probability"]]
    test_df["event_start"] = (
        test_df["event_start"].dt.tz_localize("UTC").dt.tz_convert(sensor.timezone)
    )
    test_df["belief_time"] = (
        test_df["belief_time"].dt.tz_localize("UTC").dt.tz_convert(sensor.timezone)
    )

    # Build forecast DataFrame
    forecast_df = pd.DataFrame(
        {
            "forecasts": test_df["forecasts"].values,
            "cumulative_probability": test_df["cumulative_probability"].values,
        },
        index=pd.MultiIndex.from_arrays(
            [test_df["event_start"], test_df["belief_time"]],
            names=["event_start", "belief_time"],
        ),
    )

    # Set up forecaster regressors attributes to be saved on the datasource
    # use sensor names from the database and id's in attribute
    # use sensor names from cli command for model name

    if "autoregressive" in regressors:
        regressors_names = "autoregressive"
        sensor = Sensor.query.get(sensors[target_sensor])
        regressors_attribute = f"(autoregressive) {sensor.name}: {sensor.id}"
    else:
        regressor_pairs = []
        for sensor_name, sensor_id in sensors.items():
            if sensor_name in regressors:
                sensor = Sensor.query.get(sensor_id)
                regressor_pairs.append(f"{sensor.name}: {sensor.id}")
        regressors_attribute = ", ".join(regressor_pairs)
        regressors_names = ", ".join(regressors)

    data_source = get_or_create_source(
        source="forecaster",
        model=f"CustomLGBM ({regressors_names})",
        source_type="forecaster",
        attributes={"regressors": regressors_attribute},
    )

    # Convert to TimedBelief list
    ts_value_forecasts = [
        TimedBelief(
            event_start=event_start,
            belief_time=belief_time,
            event_value=row["forecasts"],
            cumulative_probability=row["cumulative_probability"],
            sensor=sensor_to_save,
            source=data_source,
        )
        for (event_start, belief_time), row in forecast_df.iterrows()
    ]

    return tb.BeliefsDataFrame(ts_value_forecasts)


def floor_to_resolution(dt: datetime, resolution: timedelta) -> datetime:
    delta_seconds = resolution.total_seconds()
    floored = dt.timestamp() - (dt.timestamp() % delta_seconds)
    return datetime.fromtimestamp(floored, tz=dt.tzinfo)
