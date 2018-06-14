from typing import List, Tuple, Union

from flask import session
import numpy as np
import pandas as pd

from bvp.utils import time_utils, calculations
from bvp.data.services import get_prices, get_weather, extract_forecasts, Resource


def get_power_data(
    showing_pure_consumption_data: bool, metrics: dict
) -> Tuple[pd.DataFrame, Union[None, pd.DataFrame], dict]:
    """Get power data and metrics"""
    power_data = Resource(session["resource"]).get_data()
    if showing_pure_consumption_data:
        power_data *= -1
    power_forecast_data = extract_forecasts(power_data)
    power_hour_factor = time_utils.resolution_to_hour_factor(session["resolution"])
    realised_power_in_mwh = pd.Series(power_data.y * power_hour_factor).values

    if not power_data.empty:
        metrics["realised_power_in_mwh"] = realised_power_in_mwh.sum()
    if not power_forecast_data.empty:
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
    prices_data = get_prices(["epex_da"])
    metrics["realised_unit_price"] = prices_data.y.mean()
    prices_forecast_data = extract_forecasts(prices_data)
    if not prices_forecast_data.empty:
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
    weather_data = get_weather(
        [weather_type],
        session["start_time"],
        session["end_time"],
        session["resolution"],
    )
    return weather_data, None, weather_type, metrics


def get_revenues_costs_data(
    power_data: pd.DataFrame,
    prices_data: pd.DataFrame,
    power_forecast_data: pd.DataFrame,
    prices_forecast_data: pd.DataFrame,
    metrics: dict,
) -> Tuple[pd.Series, Union[None, pd.DataFrame], dict]:
    """Compute Revenues/costs data. These data are purely derivative from power and prices.
    For forecasts we use the WAPE metrics. Then we calculate metrics on this construct."""
    rev_cost_data = pd.Series()
    rev_cost_forecasts = pd.DataFrame()
    if power_data.empty or prices_data.empty:
        metrics["realised_revenues_costs"] = np.NaN
    else:
        rev_cost_data = pd.Series(power_data.y * prices_data.y, index=power_data.index)
        metrics["realised_revenues_costs"] = rev_cost_data.values.sum()

    if (
        power_data.empty
        or prices_data.empty
        or power_forecast_data.empty
        or prices_forecast_data.empty
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
