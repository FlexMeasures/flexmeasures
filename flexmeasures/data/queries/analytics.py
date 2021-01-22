from typing import List, Dict, Tuple, Union
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import timely_beliefs as tb

from flexmeasures.data.queries.utils import (
    simplify_index,
    multiply_dataframe_with_deterministic_beliefs,
)
from flexmeasures.data.services.time_series import set_bdf_source
from flexmeasures.utils import calculations, time_utils
from flexmeasures.data.services.resources import Resource, find_closest_weather_sensor
from flexmeasures.data.models.assets import Asset, Power
from flexmeasures.data.models.markets import Market, Price
from flexmeasures.data.models.weather import Weather, WeatherSensor, WeatherSensorType


def get_power_data(
    resource: Union[str, Resource],  # name or instance
    show_consumption_as_positive: bool,
    showing_individual_traces_for: str,
    metrics: dict,
    query_window: Tuple[datetime, datetime],
    resolution: str,
    forecast_horizon: timedelta,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Get power data and metrics.

    Return power observations, power forecasts and power schedules (each might be an empty DataFrame)
    and a dict with the following metrics:
    - expected value
    - mean absolute error
    - mean absolute percentage error
    - weighted absolute percentage error

    Todo: Power schedules ignore horizon.
    """
    if isinstance(resource, str):
        resource = Resource(resource)

    default_columns = ["event_value", "belief_horizon", "source"]

    # Get power data
    if showing_individual_traces_for != "schedules":
        resource.load_sensor_data(
            sensor_types=[Power],
            start=query_window[0],
            end=query_window[-1],
            resolution=resolution,
            belief_horizon_window=(None, timedelta(hours=0)),
            exclude_source_types=["scheduling script"],
        )
        if showing_individual_traces_for == "power":
            power_bdf = resource.power_data
            # In this case, power_bdf is actually a dict of BeliefDataFrames.
            # We join the frames into one frame, remembering -per frame- the sensor name as source.
            power_bdf = pd.concat(
                [
                    set_bdf_source(bdf, sensor_name)
                    for sensor_name, bdf in power_bdf.items()
                ]
            )
        else:
            # Here, we aggregate all rows together
            power_bdf = resource.aggregate_power_data
        power_df: pd.DataFrame = simplify_index(
            power_bdf, index_levels_to_columns=["belief_horizon", "source"]
        )
        if showing_individual_traces_for == "power":
            # In this case, we keep on indexing by source (as we have more than one)
            power_df.set_index("source", append=True, inplace=True)
    else:
        power_df = pd.DataFrame(columns=default_columns)

    # Get power forecast
    if showing_individual_traces_for == "none":
        power_forecast_bdf: tb.BeliefsDataFrame = resource.load_sensor_data(
            sensor_types=[Power],
            start=query_window[0],
            end=query_window[-1],
            resolution=resolution,
            belief_horizon_window=(forecast_horizon, None),
            exclude_source_types=["scheduling script"],
        ).aggregate_power_data
        power_forecast_df: pd.DataFrame = simplify_index(
            power_forecast_bdf, index_levels_to_columns=["belief_horizon", "source"]
        )
    else:
        power_forecast_df = pd.DataFrame(columns=default_columns)

    # Get power schedule
    if showing_individual_traces_for != "power":
        resource.load_sensor_data(
            sensor_types=[Power],
            start=query_window[0],
            end=query_window[-1],
            resolution=resolution,
            belief_horizon_window=(None, None),
            source_types=["scheduling script"],
        )
        if showing_individual_traces_for == "schedules":
            power_schedule_bdf = resource.power_data
            power_schedule_bdf = pd.concat(
                [
                    set_bdf_source(bdf, sensor_name)
                    for sensor_name, bdf in power_schedule_bdf.items()
                ]
            )
        else:
            power_schedule_bdf = resource.aggregate_power_data
        power_schedule_df: pd.DataFrame = simplify_index(
            power_schedule_bdf, index_levels_to_columns=["belief_horizon", "source"]
        )
        if showing_individual_traces_for == "schedules":
            power_schedule_df.set_index("source", append=True, inplace=True)
    else:
        power_schedule_df = pd.DataFrame(columns=default_columns)

    if show_consumption_as_positive:
        power_df["event_value"] *= -1
        power_forecast_df["event_value"] *= -1
        power_schedule_df["event_value"] *= -1

    # Calculate the power metrics
    power_hour_factor = time_utils.resolution_to_hour_factor(resolution)
    realised_power_in_mwh = pd.Series(
        power_df["event_value"] * power_hour_factor
    ).values

    if not power_df.empty:
        metrics["realised_power_in_mwh"] = np.nansum(realised_power_in_mwh)
    else:
        metrics["realised_power_in_mwh"] = np.NaN
    if not power_forecast_df.empty and power_forecast_df.size == power_df.size:
        expected_power_in_mwh = pd.Series(
            power_forecast_df["event_value"] * power_hour_factor
        ).values
        metrics["expected_power_in_mwh"] = np.nansum(expected_power_in_mwh)
        metrics["mae_power_in_mwh"] = calculations.mean_absolute_error(
            realised_power_in_mwh, expected_power_in_mwh
        )
        metrics["mape_power"] = calculations.mean_absolute_percentage_error(
            realised_power_in_mwh, expected_power_in_mwh
        )
        metrics["wape_power"] = calculations.weighted_absolute_percentage_error(
            realised_power_in_mwh, expected_power_in_mwh
        )
    else:
        metrics["expected_power_in_mwh"] = np.NaN
        metrics["mae_power_in_mwh"] = np.NaN
        metrics["mape_power"] = np.NaN
        metrics["wape_power"] = np.NaN
    return power_df, power_forecast_df, power_schedule_df, metrics


def get_prices_data(
    metrics: dict,
    market: Market,
    query_window: Tuple[datetime, datetime],
    resolution: str,
    forecast_horizon: timedelta,
) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Get price data and metrics.

    Return price observations, price forecasts (either might be an empty DataFrame)
    and a dict with the following metrics:
    - expected value
    - mean absolute error
    - mean absolute percentage error
    - weighted absolute percentage error
    """

    market_name = "" if market is None else market.name

    # Get price data
    price_bdf: tb.BeliefsDataFrame = Price.collect(
        [market_name],
        query_window=query_window,
        resolution=resolution,
        belief_horizon_window=(None, timedelta(hours=0)),
    )
    price_df: pd.DataFrame = simplify_index(
        price_bdf, index_levels_to_columns=["belief_horizon", "source"]
    )

    if not price_bdf.empty:
        metrics["realised_unit_price"] = price_df["event_value"].mean()
    else:
        metrics["realised_unit_price"] = np.NaN

    # Get price forecast
    price_forecast_bdf: tb.BeliefsDataFrame = Price.collect(
        [market_name],
        query_window=query_window,
        resolution=resolution,
        belief_horizon_window=(forecast_horizon, None),
        source_types=["user", "forecasting script", "script"],
    )
    price_forecast_df: pd.DataFrame = simplify_index(
        price_forecast_bdf, index_levels_to_columns=["belief_horizon", "source"]
    )

    # Calculate the price metrics
    if not price_forecast_df.empty and price_forecast_df.size == price_df.size:
        metrics["expected_unit_price"] = price_forecast_df["event_value"].mean()
        metrics["mae_unit_price"] = calculations.mean_absolute_error(
            price_df["event_value"], price_forecast_df["event_value"]
        )
        metrics["mape_unit_price"] = calculations.mean_absolute_percentage_error(
            price_df["event_value"], price_forecast_df["event_value"]
        )
        metrics["wape_unit_price"] = calculations.weighted_absolute_percentage_error(
            price_df["event_value"], price_forecast_df["event_value"]
        )
    else:
        metrics["expected_unit_price"] = np.NaN
        metrics["mae_unit_price"] = np.NaN
        metrics["mape_unit_price"] = np.NaN
        metrics["wape_unit_price"] = np.NaN
    return price_df, price_forecast_df, metrics


def get_weather_data(
    assets: List[Asset],
    metrics: dict,
    sensor_type: WeatherSensorType,
    query_window: Tuple[datetime, datetime],
    resolution: str,
    forecast_horizon: timedelta,
) -> Tuple[pd.DataFrame, pd.DataFrame, str, WeatherSensor, dict]:
    """Get most recent weather data and forecast weather data for the requested forecast horizon.

    Return weather observations, weather forecasts (either might be an empty DataFrame),
    the name of the sensor type, the weather sensor and a dict with the following metrics:
    - expected value
    - mean absolute error
    - mean absolute percentage error
    - weighted absolute percentage error"""

    # Todo: for now we only collect weather data for a single asset
    asset = assets[0]

    weather_data = tb.BeliefsDataFrame(columns=["event_value"])
    weather_forecast_data = tb.BeliefsDataFrame(columns=["event_value"])
    sensor_type_name = ""
    closest_sensor = None
    if sensor_type:
        # Find the 50 closest weather sensors
        sensor_type_name = sensor_type.name
        closest_sensors = find_closest_weather_sensor(
            sensor_type_name, n=50, object=asset
        )
        if closest_sensors:
            closest_sensor = closest_sensors[0]

            # Collect the weather data for the requested time window
            sensor_names = [sensor.name for sensor in closest_sensors]

            # Get weather data
            weather_bdf_dict: Dict[str, tb.BeliefsDataFrame] = Weather.collect(
                sensor_names,
                query_window=query_window,
                resolution=resolution,
                belief_horizon_window=(None, timedelta(hours=0)),
                sum_multiple=False,
            )
            weather_df_dict: Dict[str, pd.DataFrame] = {}
            for sensor_name in weather_bdf_dict:
                weather_df_dict[sensor_name] = simplify_index(
                    weather_bdf_dict[sensor_name],
                    index_levels_to_columns=["belief_horizon", "source"],
                )

            # Get weather forecasts
            weather_forecast_bdf_dict: Dict[str, tb.BeliefsDataFrame] = Weather.collect(
                sensor_names,
                query_window=query_window,
                resolution=resolution,
                belief_horizon_window=(forecast_horizon, None),
                source_types=["user", "forecasting script", "script"],
                sum_multiple=False,
            )
            weather_forecast_df_dict: Dict[str, pd.DataFrame] = {}
            for sensor_name in weather_forecast_bdf_dict:
                weather_forecast_df_dict[sensor_name] = simplify_index(
                    weather_forecast_bdf_dict[sensor_name],
                    index_levels_to_columns=["belief_horizon", "source"],
                )

            # Take the closest weather sensor which contains some data for the selected time window
            for sensor, sensor_name in zip(closest_sensors, sensor_names):
                if (
                    not weather_df_dict[sensor_name]["event_value"]
                    .isnull()
                    .values.all()
                    or not weather_forecast_df_dict[sensor_name]["event_value"]
                    .isnull()
                    .values.all()
                ):
                    closest_sensor = sensor
                    break

            weather_data = weather_df_dict[sensor_name]
            weather_forecast_data = weather_forecast_df_dict[sensor_name]

            # Calculate the weather metrics
            if not weather_data.empty:
                metrics["realised_weather"] = weather_data["event_value"].mean()
            else:
                metrics["realised_weather"] = np.NaN
            if (
                not weather_forecast_data.empty
                and weather_forecast_data.size == weather_data.size
            ):
                metrics["expected_weather"] = weather_forecast_data[
                    "event_value"
                ].mean()
                metrics["mae_weather"] = calculations.mean_absolute_error(
                    weather_data["event_value"], weather_forecast_data["event_value"]
                )
                metrics["mape_weather"] = calculations.mean_absolute_percentage_error(
                    weather_data["event_value"], weather_forecast_data["event_value"]
                )
                metrics[
                    "wape_weather"
                ] = calculations.weighted_absolute_percentage_error(
                    weather_data["event_value"], weather_forecast_data["event_value"]
                )
            else:
                metrics["expected_weather"] = np.NaN
                metrics["mae_weather"] = np.NaN
                metrics["mape_weather"] = np.NaN
                metrics["wape_weather"] = np.NaN
    return (
        weather_data,
        weather_forecast_data,
        sensor_type_name,
        closest_sensor,
        metrics,
    )


def get_revenues_costs_data(
    power_data: pd.DataFrame,
    prices_data: pd.DataFrame,
    power_forecast_data: pd.DataFrame,
    prices_forecast_data: pd.DataFrame,
    metrics: Dict[str, float],
    unit_factor: float,
    resolution: str,
    showing_individual_traces: bool,
) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Compute revenues/costs data. These data are purely derivative from power and prices.
    For forecasts we use the WAPE metrics. Then we calculate metrics on this construct.
    The unit factor is used when multiplying quantities and prices, e.g. when multiplying quantities in kWh with prices
    in EUR/MWh, use a unit factor of 0.001.

    Return revenue/cost observations, revenue/cost forecasts (either might be an empty DataFrame)
    and a dict with the following metrics:
    - expected value
    - mean absolute error
    - mean absolute percentage error
    - weighted absolute percentage error
    """
    power_hour_factor = time_utils.resolution_to_hour_factor(resolution)

    rev_cost_data = multiply_dataframe_with_deterministic_beliefs(
        power_data,
        prices_data,
        result_source=None
        if showing_individual_traces
        else "Calculated from power and price data",
        multiplication_factor=power_hour_factor * unit_factor,
    )
    if power_data.empty or prices_data.empty:
        metrics["realised_revenues_costs"] = np.NaN
    else:
        metrics["realised_revenues_costs"] = np.nansum(
            rev_cost_data["event_value"].values
        )

    rev_cost_forecasts = multiply_dataframe_with_deterministic_beliefs(
        power_forecast_data,
        prices_forecast_data,
        result_source="Calculated from power and price data",
        multiplication_factor=power_hour_factor * unit_factor,
    )
    if power_forecast_data.empty or prices_forecast_data.empty:
        metrics["expected_revenues_costs"] = np.NaN
        metrics["mae_revenues_costs"] = np.NaN
        metrics["mape_revenues_costs"] = np.NaN
        metrics["wape_revenues_costs"] = np.NaN
    else:
        metrics["expected_revenues_costs"] = np.nansum(
            rev_cost_forecasts["event_value"]
        )
        metrics["mae_revenues_costs"] = calculations.mean_absolute_error(
            rev_cost_data["event_value"], rev_cost_forecasts["event_value"]
        )
        metrics["mape_revenues_costs"] = calculations.mean_absolute_percentage_error(
            rev_cost_data["event_value"], rev_cost_forecasts["event_value"]
        )
        metrics[
            "wape_revenues_costs"
        ] = calculations.weighted_absolute_percentage_error(
            rev_cost_data["event_value"], rev_cost_forecasts["event_value"]
        )

        # Todo: compute confidence interval properly - this is just a simple heuristic
        rev_cost_forecasts["yhat_upper"] = rev_cost_forecasts["event_value"] * (
            1 + metrics["wape_revenues_costs"]
        )
        rev_cost_forecasts["yhat_lower"] = rev_cost_forecasts["event_value"] * (
            1 - metrics["wape_revenues_costs"]
        )
    return rev_cost_data, rev_cost_forecasts, metrics
