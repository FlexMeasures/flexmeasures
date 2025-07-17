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
    """
    q = (
        select(old_time_series_data_model)
        .join(old_sensor_model.__class__)
        .filter(old_sensor_model.__class__.name == old_sensor_model.name)
    )
    first_value = db.session.scalars(
        q.order_by(old_time_series_data_model.event_start.asc()).limit(1)
    ).first()
    last_value = db.session.scalars(
        q.order_by(old_time_series_data_model.event_start.desc()).limit(1)
    ).first()
    if first_value is None:
        raise NotEnoughDataException(
            "No data available at all. Forecasting impossible."
        )
    first = as_server_time(first_value.event_start)
    last = as_server_time(last_value.event_start)
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
    horizon : int
        Maximum forecast horizon based on sensor resolution (e.g., 48 for a 1-hour sensor or 4*48 for a 15-minute sensor).
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
    test_df = pd.DataFrame()
    df = data.copy()
    df.reset_index(inplace=True)
    df.pop("component")

    # First, rename target to '0h' for consistency
    df = df.rename(columns={target_sensor: "0h"})
    df["event_start"] = pd.to_datetime(df["event_start"])
    df["belief_time"] = pd.to_datetime(df["belief_time"])
    datetime_column = []
    belief_column = []
    forecasts_column = []
    probabilistic_column = []
    probabilistic_values = (
        [float(x.rsplit("_", 1)[-1]) for x in data.index.get_level_values("component")]
        if probabilistic
        else [0.5] * len(df["event_start"])
    )

    for i in range(len(df["event_start"])):
        date = df["event_start"][i]
        preds_timestamps = (
            []
        )  # timestamps for the event_start of the forecasts for each horizon
        forecasts = []
        for h in range(1, horizon + 1):
            time_add = (
                sensor.event_resolution * h
            )  # Calculate the time increment for each forecast horizon based on the sensor's event resolution.
            preds_timestamps.append(date + time_add)
            forecasts.append(df[f"{h}h"][i])

        forecasts_column.extend(forecasts)
        datetime_column.extend(preds_timestamps)
        belief_column.extend([df["belief_time"][i]] * h)
        probabilistic_column.extend([probabilistic_values[i]] * h)

    test_df["event_start"] = datetime_column
    test_df["belief_time"] = belief_column
    test_df["forecasts"] = forecasts_column
    test_df["event_start"] = (
        test_df["event_start"].dt.tz_localize("UTC").dt.tz_convert(sensor.timezone)
    )
    test_df["belief_time"] = (
        test_df["belief_time"].dt.tz_localize("UTC").dt.tz_convert(sensor.timezone)
    )

    test_df["cumulative_probability"] = probabilistic_column

    bdf = test_df.copy()

    forecast_df = pd.DataFrame(
        {
            "forecasts": bdf["forecasts"].values,
            "cumulative_probability": bdf["cumulative_probability"].values,
        },
        index=pd.MultiIndex.from_arrays(
            [bdf["event_start"], bdf["belief_time"]],
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

    bdf = tb.BeliefsDataFrame(ts_value_forecasts)

    return bdf
