from typing import List, Dict, Tuple
from datetime import timedelta

from flask import session
import numpy as np
import pandas as pd
import timely_beliefs as tb

from bvp.data.queries.utils import simplify_index
from bvp.utils import calculations, time_utils
from bvp.data.services.resources import Resource, find_closest_weather_sensor
from bvp.data.models.assets import Asset
from bvp.data.models.markets import Market, Price
from bvp.data.models.weather import Weather, WeatherSensor, WeatherSensorType


def get_power_data(
    show_consumption_as_positive: bool, metrics: dict
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

    query_window, resolution = time_utils.ensure_timing_vars_are_set(
        (session["start_time"], session["end_time"]), session["resolution"]
    )

    # Get power data
    power_bdf: tb.BeliefsDataFrame = Resource(session["resource"]).get_data(
        start=query_window[0],
        end=query_window[-1],
        resolution=resolution,
        horizon_window=(None, timedelta(hours=0)),
        rolling=True,
    )
    power_df: pd.DataFrame = simplify_index(
        power_bdf, index_levels_to_columns=["belief_horizon", "source"]
    )

    # Get power forecast
    horizon = pd.to_timedelta(session["forecast_horizon"])
    power_forecast_bdf: tb.BeliefsDataFrame = Resource(session["resource"]).get_data(
        start=query_window[0],
        end=query_window[-1],
        resolution=resolution,
        horizon_window=(horizon, None),
        rolling=True,
        source_types=[
            "user",
            "forecasting script",
            "script",
        ],  # we choose to show data from scheduling scripts separately
    )
    power_forecast_df: pd.DataFrame = simplify_index(
        power_forecast_bdf, index_levels_to_columns=["belief_horizon", "source"]
    )

    # Get power schedule
    power_schedule_bdf: tb.BeliefsDataFrame = Resource(session["resource"]).get_data(
        start=query_window[0],
        end=query_window[-1],
        resolution=resolution,
        horizon_window=(None, None),
        source_types=["scheduling script"],
    )
    power_schedule_df: pd.DataFrame = simplify_index(
        power_schedule_bdf, index_levels_to_columns=["belief_horizon", "source"]
    )

    if show_consumption_as_positive:
        power_df["event_value"] *= -1
        power_forecast_df["event_value"] *= -1
        power_schedule_df["event_value"] *= -1

    # Calculate the power metrics
    power_hour_factor = time_utils.resolution_to_hour_factor(session["resolution"])
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
    metrics: dict, market: Market
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
    query_window, resolution = time_utils.ensure_timing_vars_are_set(
        (session["start_time"], session["end_time"]), session["resolution"]
    )

    # Get price data
    price_bdf: tb.BeliefsDataFrame = Price.collect(
        [market_name],
        query_window=query_window,
        resolution=resolution,
        horizon_window=(None, timedelta(hours=0)),
        rolling=True,
    )
    price_df: pd.DataFrame = simplify_index(
        price_bdf, index_levels_to_columns=["belief_horizon", "source"]
    )

    if not price_bdf.empty:
        metrics["realised_unit_price"] = price_df["event_value"].mean()
    else:
        metrics["realised_unit_price"] = np.NaN

    # Get price forecast
    horizon = pd.to_timedelta(session["forecast_horizon"])
    price_forecast_bdf: tb.BeliefsDataFrame = Price.collect(
        [market_name],
        query_window=query_window,
        resolution=resolution,
        horizon_window=(horizon, None),
        rolling=True,
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
    assets: List[Asset], metrics: dict, sensor_type: WeatherSensorType
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
            query_window, resolution = time_utils.ensure_timing_vars_are_set(
                (session["start_time"], session["end_time"]), session["resolution"]
            )

            # Get weather data
            weather_bdf_dict: Dict[str, tb.BeliefsDataFrame] = Weather.collect(
                sensor_names,
                query_window=query_window,
                resolution=resolution,
                horizon_window=(None, timedelta(hours=0)),
                rolling=True,
                sum_multiple=False,
            )
            weather_df_dict: Dict[str, pd.DataFrame] = {}
            for sensor_name in weather_bdf_dict:
                weather_df_dict[sensor_name] = simplify_index(
                    weather_bdf_dict[sensor_name],
                    index_levels_to_columns=["belief_horizon", "source"],
                )

            # Get weather forecasts
            horizon = pd.to_timedelta(session["forecast_horizon"])
            weather_forecast_bdf_dict: Dict[str, tb.BeliefsDataFrame] = Weather.collect(
                sensor_names,
                query_window=query_window,
                resolution=resolution,
                horizon_window=(horizon, None),
                rolling=True,
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
    power_hour_factor = time_utils.resolution_to_hour_factor(session["resolution"])
    rev_cost_data = tb.BeliefsDataFrame(
        index=power_data.index,
        sensor=power_data.sensor,
        columns=["event_value", "belief_horizon", "source"],
    )
    rev_cost_data = simplify_index(rev_cost_data)

    rev_cost_forecasts = tb.BeliefsDataFrame(
        index=power_data.index,
        sensor=power_data.sensor,
        columns=["event_value", "yhat_upper", "yhat_lower"],
    )
    rev_cost_forecasts = simplify_index(rev_cost_forecasts)

    if power_data.empty or prices_data.empty:
        metrics["realised_revenues_costs"] = np.NaN
    else:
        rev_cost_data = tb.BeliefsDataFrame(
            dict(
                event_value=power_data["event_value"]
                * power_hour_factor
                * prices_data["event_value"]
                * unit_factor
            ),
            index=power_data.index,
            sensor=power_data.sensor,
        )
        rev_cost_data = simplify_index(rev_cost_data)
        if (
            "belief_horizon" in power_data.columns
            and "belief_horizon" in prices_data.columns
        ):
            rev_cost_data["belief_horizon"] = pd.DataFrame(
                [power_data["belief_horizon"], prices_data["belief_horizon"]]
            ).min()
        if "source" in power_data.columns and "source" in prices_data.columns:
            rev_cost_data["source"] = "Calculated from power and price data"
        metrics["realised_revenues_costs"] = np.nansum(
            rev_cost_data["event_value"].values
        )

    if (
        power_data.empty
        or prices_data.empty
        or power_forecast_data.empty
        or prices_forecast_data.empty
        or not (power_data["event_value"].size == prices_data["event_value"].size)
        or not (
            power_forecast_data["event_value"].size
            == prices_forecast_data["event_value"].size
        )
    ):
        metrics["expected_revenues_costs"] = np.NaN
        metrics["mae_revenues_costs"] = np.NaN
        metrics["mape_revenues_costs"] = np.NaN
        metrics["wape_revenues_costs"] = np.NaN
    else:
        rev_cost_forecasts = tb.BeliefsDataFrame(
            index=power_data.index,
            sensor=power_data.sensor,
            columns=["event_value", "yhat_upper", "yhat_lower"],
        )
        rev_cost_forecasts = simplify_index(rev_cost_forecasts)

        if not (power_forecast_data.empty and prices_forecast_data.empty):
            rev_cost_forecasts["event_value"] = (
                power_forecast_data["event_value"]
                * power_hour_factor
                * prices_forecast_data["event_value"]
                * unit_factor
            )
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
            1 + metrics["wape_revenues_costs"] / 100
        )
        rev_cost_forecasts["yhat_lower"] = rev_cost_forecasts["event_value"] * (
            1 - metrics["wape_revenues_costs"] / 100
        )
    return rev_cost_data, rev_cost_forecasts, metrics
