from typing import List, Tuple, Union
from datetime import timedelta

from flask import session
import numpy as np
import pandas as pd

from bvp.utils import time_utils, calculations
from bvp.data.services.resources import Resource
from bvp.data.models.markets import Price
from bvp.data.models.weather import Weather


def get_power_data(
    showing_pure_consumption_data: bool, metrics: dict
) -> Tuple[pd.DataFrame, Union[None, pd.DataFrame], dict]:
    """Get power data and metrics"""

    # Get power data
    power_data = Resource(session["resource"]).get_data(create_if_empty=True)
    if showing_pure_consumption_data:
        power_data.y *= -1

    # Get power forecast
    horizon = pd.to_timedelta(session["forecast_horizon"])
    power_forecast_data = Resource(session["resource"]).get_data(
        horizon_window=(horizon, None), rolling=True, create_if_empty=True
    )
    power_forecast_data.rename(columns={"y": "yhat"}, inplace=True)
    power_hour_factor = time_utils.resolution_to_hour_factor(session["resolution"])
    realised_power_in_mwh = pd.Series(power_data.y * power_hour_factor).values

    if not power_data.empty:
        metrics["realised_power_in_mwh"] = realised_power_in_mwh.sum()
    if not power_forecast_data.empty and power_forecast_data.size == power_data.size:
        expected_power_in_mwh = pd.Series(
            power_forecast_data.yhat * power_hour_factor
        ).values
        metrics["expected_power_in_mwh"] = expected_power_in_mwh.sum()
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
    return power_data, power_forecast_data, metrics


def get_prices_data(
    metrics: dict
) -> Tuple[pd.DataFrame, Union[None, pd.DataFrame], dict]:
    """Get price data and metrics"""
    prices_data = Price.collect(["epex_da"], create_if_empty=True)
    metrics["realised_unit_price"] = prices_data.y.mean()
    prices_forecast_data = Price.collect(
        ["epex_da"], horizon_window=(timedelta(hours=48), timedelta(hours=48))
    )
    if not prices_forecast_data.empty and prices_forecast_data.size == prices_data.size:
        metrics["expected_unit_price"] = prices_forecast_data.yhat.mean()
        metrics["mae_unit_price"] = calculations.mean_absolute_error(
            prices_data.y, prices_forecast_data.yhat
        )
        metrics["mape_unit_price"] = calculations.mean_absolute_percentage_error(
            prices_data.y, prices_forecast_data.yhat
        )
        metrics["wape_unit_price"] = calculations.weighted_absolute_percentage_error(
            prices_data.y, prices_forecast_data.yhat
        )
    else:
        metrics["expected_unit_price"] = np.NaN
        metrics["mae_unit_price"] = np.NaN
        metrics["mape_unit_price"] = np.NaN
        metrics["wape_unit_price"] = np.NaN
    return prices_data, prices_forecast_data, metrics


def get_weather_data(
    session_asset_types: List[str], metrics: dict
) -> Tuple[pd.DataFrame, Union[None, pd.DataFrame], str, dict]:
    """Get weather data. No metrics yet, as we do not forecast this. It *is* forecast data we get from elsewhere."""
    if session_asset_types[0] == "wind":
        weather_type = "wind_speed"
    elif session_asset_types[0] == "solar":
        weather_type = "total_radiation"
    else:
        weather_type = "temperature"
    weather_data = Weather.collect([weather_type], create_if_empty=True)
    return weather_data, None, weather_type, metrics


def get_revenues_costs_data(
    power_data: pd.DataFrame,
    prices_data: pd.DataFrame,
    power_forecast_data: pd.DataFrame,
    prices_forecast_data: pd.DataFrame,
    metrics: dict,
) -> Tuple[pd.DataFrame, Union[None, pd.DataFrame], dict]:
    """Compute Revenues/costs data. These data are purely derivative from power and prices.
    For forecasts we use the WAPE metrics. Then we calculate metrics on this construct."""
    rev_cost_data = pd.DataFrame(
        index=power_data.index, columns=["y", "horizon", "label"]
    )
    rev_cost_forecasts = pd.DataFrame(
        index=power_data.index, columns=["yhat", "yhat_upper", "yhat_lower"]
    )
    if power_data.empty or prices_data.empty:
        metrics["realised_revenues_costs"] = np.NaN
    else:
        rev_cost_data = pd.DataFrame(
            dict(
                y=power_data.y * prices_data.y,
                horizon=pd.DataFrame([power_data.horizon, prices_data.horizon]).min(),
                label=power_data.label,
            ),
            index=power_data.index,
        )
        metrics["realised_revenues_costs"] = rev_cost_data.y.values.sum()

    if (
        power_data.empty
        or prices_data.empty
        or power_forecast_data.empty
        or prices_forecast_data.empty
        or not (
            power_data.size
            == power_forecast_data.size
            == prices_data.size
            == prices_forecast_data.size
        )
    ):
        metrics["expected_revenues_costs"] = np.NaN
        metrics["mae_revenues_costs"] = np.NaN
        metrics["mape_revenues_costs"] = np.NaN
    else:
        rev_cost_forecasts = pd.DataFrame(
            index=power_data.index, columns=["yhat", "yhat_upper", "yhat_lower"]
        )
        if not (power_forecast_data.empty and prices_forecast_data.empty):
            rev_cost_forecasts.yhat = (
                power_forecast_data.yhat * prices_forecast_data.yhat
            )
        # factor for confidence interval - there might be a better heuristic here
        wape_factor_rev_costs = (
            metrics["wape_power"] / 100. + metrics["wape_unit_price"] / 100.
        ) / 2.
        wape_span_rev_costs = rev_cost_forecasts.yhat * wape_factor_rev_costs
        rev_cost_forecasts.yhat_upper = rev_cost_forecasts.yhat + wape_span_rev_costs
        rev_cost_forecasts.yhat_lower = rev_cost_forecasts.yhat - wape_span_rev_costs
        metrics["expected_revenues_costs"] = rev_cost_forecasts.yhat.sum()
        metrics["mae_revenues_costs"] = calculations.mean_absolute_error(
            rev_cost_data.values, rev_cost_forecasts.yhat
        )
        metrics["mape_revenues_costs"] = calculations.mean_absolute_percentage_error(
            rev_cost_data.values, rev_cost_forecasts.yhat
        )
        metrics[
            "wape_revenues_costs"
        ] = calculations.weighted_absolute_percentage_error(
            rev_cost_data.values, rev_cost_forecasts.yhat
        )
    return rev_cost_data, rev_cost_forecasts, metrics
