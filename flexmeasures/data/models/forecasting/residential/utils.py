import os

import numpy as np
import pandas as pd
import timely_beliefs as tb
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.utils import get_data_source


def _get_source_from_path(path: str) -> tb.BeliefSource:
    """
    Extracts the belief source identifier from a given file path and returns a BeliefSource object.

    The function performs the following steps:
    1. Extracts the file name from the given pzath.
    2. Removes the file extension from the file name.
    3. Splits the file name by underscores and selects parts from the 7th element onwards.
    4. Joins these parts back together with underscores to form the belief source identifier.
    5. Creates and returns a BeliefSource object initialized with the identifier.

    Example:
    "df_48_hour_heating_demand_point_rf.csv" -> "rf"
    "df_48_hour_heating_demand_probabilistic_lgbm.csv" -> "lgbm"
    """
    file_name_with_extension = os.path.split(path)[-1]
    file_name = os.path.splitext(file_name_with_extension)[0]

    # Splitting the file name by underscore and selecting parts from the 7th element onwards
    belief_source_parts = file_name.split("_")[6:]
    belief_source_identifier = "_".join(belief_source_parts)
    belief_source = tb.BeliefSource(belief_source_identifier)

    return belief_source


def csv_to_bdf(path: str, nrows: int, probabilistic: bool) -> tb.BeliefsDataFrame:
    sensor = tb.Sensor(
        "heating demand", unit="W", event_resolution=pd.Timedelta(hours=1)
    )
    source = _get_source_from_path(path)
    timezone = "Europe/Amsterdam"

    # Read the CSV file
    df = pd.read_csv(path, nrows=nrows).rename(
        {
            "datetime": "belief_time",
            "heating demand": "0h",
        },
        axis=1,
    )

    if probabilistic:
        # Extract cumulative probability from the 'component' column and drop it
        df["cumulative_probability"] = (
            df["component"].str.extract(r"(\d+\.\d+)").astype(float)
        )
        df = df.drop(columns=["component"])
        id_vars = ["belief_time", "cumulative_probability"]
    else:
        id_vars = ["belief_time"]

    df = pd.melt(
        df,
        id_vars=id_vars,
        value_vars=[col for col in df.columns if col not in id_vars],
        var_name="belief_horizon",
        value_name="event_value",
    )

    # Ensure correct dtypes
    df["belief_time"] = pd.to_datetime(
        df["belief_time"], infer_datetime_format=True
    ).dt.tz_localize(timezone)
    df["belief_horizon"] = pd.to_timedelta(df["belief_horizon"])
    df["event_start"] = (
        df["belief_time"] + df["belief_horizon"] - sensor.event_resolution
    )

    # Create the BeliefsDataFrame
    bdf_kwargs = {
        "sensor": sensor,
        "source": source,
    }
    if probabilistic:
        bdf_kwargs["cumulative_probability"] = df["cumulative_probability"].values

    bdf = tb.BeliefsDataFrame(df, **bdf_kwargs)
    return bdf


def negative_to_zero(x: np.ndarray) -> np.ndarray:
    return np.where(x < 0, 0, x)


def data_to_bdf(
    data: pd.DataFrame,
    horizon: int,
    probabilistic: bool,
    sensors: dict[str, int],
    target_sensor: str,
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
    df["datetime"] = pd.to_datetime(df["datetime"])
    datetime_column = []
    belief_column = []
    forecasts_column = []
    probabilistic_column = []
    probabilistic_values = (
        [float(x.rsplit("_", 1)[-1]) for x in data.index.get_level_values("component")]
        if probabilistic
        else [0.5] * len(df["datetime"])
    )
    for i in range(len(df["datetime"])):
        date = df["datetime"][i]
        preds_timestamps = (
            []
        )  # timestamps for the event_start of the forecasts for each horizon
        forecasts = []
        for horizon in range(1, horizon + 1):
            time_add = (
                sensor.event_resolution * horizon
            )  # Calculate the time increment for each forecast horizon based on the sensor's event resolution.
            preds_timestamps.append(date + time_add)
            forecasts.append(df[f"{horizon}h"][i])

        forecasts_column.extend(forecasts)
        datetime_column.extend(preds_timestamps)
        belief_column.extend([date + sensor.event_resolution] * (horizon))
        probabilistic_column.extend([probabilistic_values[i]] * horizon)

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

    data_source = get_data_source(
        data_source_name="forecaster",
        data_source_type="forecaster",
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
