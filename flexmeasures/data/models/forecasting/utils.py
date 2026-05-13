from __future__ import annotations

import numpy as np
import pandas as pd
import timely_beliefs as tb
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import Sensor

from datetime import datetime, timedelta

from flexmeasures.data import db


def negative_to_zero(x: np.ndarray) -> np.ndarray:
    return np.where(x < 0, 0, x)


def data_to_bdf(
    data: pd.DataFrame,
    horizon: int,
    probabilistic: bool,
    target_sensor: Sensor,
    sensor_to_save: Sensor,
    data_source: DataSource,
) -> tb.BeliefsDataFrame:
    """
    Converts a prediction DataFrame into a BeliefsDataFrame for saving to the database.

    :param data:            DataFrame containing predictions for different forecast horizons.
                            If probabilistic forecasts are generated, `data` includes a `component` column,
                            which encodes which quantile (cumulative probability) the row corresponds to.
    :param horizon:         Maximum forecast horizon in time-steps relative to the sensor's resolution.
                            For example, if the sensor resolution is 1 hour, a horizon of 48 represents
                            a forecast horizon of 48 hours. Similarly, if the sensor resolution is 15 minutes,
                            a horizon of 4*48 represents a forecast horizon of 48 hours.
    :param probabilistic:   Whether the forecasts are probabilistic or deterministic.
    :param target_sensor:   The Sensor object for which the predictions are made.
    :param sensor_to_save:  The Sensor object to save the forecasts to.
    :param data_source:     The DataSource object to attribute the forecasts to.
    :returns:               A formatted BeliefsDataFrame ready for database insertion.
    """
    df = data.copy()
    df.reset_index(inplace=True)

    # Rename target to '0h'
    df = df.rename(columns={f"{target_sensor.name} (ID: {target_sensor.id})": "0h"})
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
        lambda h: target_sensor.event_resolution * h
    )

    # Forecast values
    expanded["forecasts"] = expanded.apply(lambda r: r[f"{r.h}h"], axis=1)

    # Probabilities (repeat original values across horizons)
    expanded["cumulative_probability"] = np.repeat(probabilistic_values, horizon)

    # Cleanup
    test_df = expanded[
        ["event_start", "belief_time", "forecasts", "cumulative_probability"]
    ].copy()
    test_df["event_start"] = (
        test_df["event_start"]
        .dt.tz_localize("UTC")
        .dt.tz_convert(target_sensor.timezone)
    )
    test_df["belief_time"] = (
        test_df["belief_time"]
        .dt.tz_localize("UTC")
        .dt.tz_convert(target_sensor.timezone)
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

    # # Set up forecaster regressors attributes to be saved on the datasource
    # # use sensor names from the database and id's in attribute
    # # use sensor names from cli command for model name
    #
    # if "autoregressive" in regressors:
    #     regressors_names = "autoregressive"
    # else:
    #     regressors_names = ", ".join(regressors)
    #
    # data_source = get_or_create_source(
    #     source="forecaster",
    #     model=f"CustomLGBM ({regressors_names})",
    #     source_type="forecaster",
    #     attributes=self.data_source.attributes,
    # )
    source = refresh_data_source(data_source)

    # Convert to BeliefsDataFrame
    bdf = tb.BeliefsDataFrame(
        forecast_df.reset_index().rename(columns={"forecasts": "event_value"}),
        source=source,
        sensor=sensor_to_save,
    )
    return bdf


def floor_to_resolution(dt: datetime, resolution: timedelta) -> datetime:
    delta_seconds = resolution.total_seconds()
    floored = dt.timestamp() - (dt.timestamp() % delta_seconds)
    return datetime.fromtimestamp(floored, tz=dt.tzinfo)


def refresh_data_source(data_source: DataSource) -> DataSource:
    """Refresh the potentially detached data source.

    This avoids a sqlalchemy.exc.IntegrityError / psycopg2.errors.ForeignKeyViolation
    for the data source ID not being present in the data_source table.

    Prefer looking up by ID when available: this sidesteps the ``attributes_hash``
    mismatch that arises because PostgreSQL JSONB returns keys in alphabetical order,
    while the stored hash was originally computed from the Python insertion-order dict.
    """

    if data_source.id is not None:
        refreshed = db.session.get(DataSource, data_source.id)
        if refreshed is not None:
            return refreshed

    from flexmeasures.data.services.data_sources import get_or_create_source

    return get_or_create_source(
        data_source.name,
        source_type=data_source.type,
        model=data_source.model,
        version=data_source.version,
        attributes=data_source.attributes,
    )
