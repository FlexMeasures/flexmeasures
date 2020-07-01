from typing import List, Optional, Union, Tuple, Dict
from datetime import timedelta
import io
import csv
import json
import math

import pandas as pd
from flask import session, current_app, make_response
from flask_security import roles_accepted
from bokeh.plotting import Figure
from bokeh.embed import components
from bokeh.util.string import encode_utf8
from bokeh.models import Range1d

from bvp.data.models.markets import Market
from bvp.data.models.weather import WeatherSensor
from bvp.data.services.resources import (
    get_assets,
    get_asset_group_queries,
    get_markets,
    get_sensor_types,
    Resource,
)
from bvp.data.services.time_series import ensure_timing_vars_are_set
from bvp.data.queries.analytics import (
    get_power_data,
    get_prices_data,
    get_weather_data,
    get_revenues_costs_data,
)
from bvp.utils import time_utils
from bvp.utils.bvp_inflection import humanize
from bvp.ui.utils.view_utils import (
    render_bvp_template,
    set_session_resource,
    set_session_market,
    set_session_sensor_type,
)
from bvp.ui.utils.plotting_utils import create_graph, separate_legend
from bvp.ui.views import bvp_ui


@bvp_ui.route("/analytics", methods=["GET", "POST"])
@roles_accepted("admin", "Prosumer")
def analytics_view():
    """ Analytics view. Here, four plots (consumption/generation, weather, prices and a profit/loss calculation)
    and a table of metrics data are prepared. This view allows to select a resource name, from which a
    models.Resource object can be made. The resource name is kept in the session.
    Based on the resource, plots and table are labelled appropriately.
    """
    time_utils.set_time_range_for_session()
    markets = get_markets()
    assets = get_assets()
    asset_groups = get_asset_group_queries(
        custom_additional_groups=[
            "renewables",
            "all Charge Points",
            "each Charge Point",
        ]
    )
    asset_group_names: List[str] = [
        group for group in asset_groups if asset_groups[group].count() > 0
    ]
    selected_resource = set_session_resource(assets, asset_group_names)
    selected_market = set_session_market(selected_resource)
    sensor_types = get_sensor_types(selected_resource)
    selected_sensor_type = set_session_sensor_type(sensor_types)
    session_asset_types = Resource(session["resource"]).unique_asset_types

    # This is useful information - we might want to adapt the sign of the data and labels.
    showing_pure_consumption_data = all(
        [a.is_pure_consumer for a in Resource(session["resource"]).assets]
    )
    showing_pure_production_data = all(
        [a.is_pure_producer for a in Resource(session["resource"]).assets]
    )
    # Only show production positive if all assets are producers
    show_consumption_as_positive = False if showing_pure_production_data else True

    data, metrics, weather_type, selected_weather_sensor = get_data_and_metrics(
        show_consumption_as_positive,
        selected_market,
        selected_sensor_type,
        Resource(session["resource"]).assets,
    )

    # Set shared x range
    series = time_utils.tz_index_naively(data["power"].index)
    if not series.empty:
        shared_x_range = Range1d(
            start=min(series),
            end=max(series) + pd.to_timedelta(data["power"].index.freq),
        )
    else:
        query_window, resolution = ensure_timing_vars_are_set((None, None), None)
        shared_x_range = Range1d(
            start=query_window[0], end=query_window[1] + pd.to_timedelta(resolution)
        )

    # TODO: get rid of this hack, which we use because we mock 2015 data in demo mode
    if current_app.config.get("BVP_MODE", "") == "demo":

        # Show only past data, pretending we're in 2015
        if not data["power"].empty:
            data["power"] = data["power"].loc[
                data["power"].index
                < time_utils.get_most_recent_quarter().replace(year=2015)
            ]
        if not data["prices"].empty:
            data["prices"] = data["prices"].loc[
                data["prices"].index
                < time_utils.get_most_recent_quarter().replace(year=2015)
                + timedelta(hours=24)
            ]  # keep tomorrow's prices
        if not data["weather"].empty:
            data["weather"] = data["weather"].loc[
                data["weather"].index
                < time_utils.get_most_recent_quarter().replace(year=2015)
            ]
        if not data["rev_cost"].empty:
            data["rev_cost"] = data["rev_cost"].loc[
                data["rev_cost"].index
                < time_utils.get_most_recent_quarter().replace(year=2015)
            ]

        # Show forecasts only up to a limited horizon
        horizon_days = 10  # keep a 10 day forecast
        if not data["power_forecast"].empty:
            data["power_forecast"] = data["power_forecast"].loc[
                data["power_forecast"].index
                < time_utils.get_most_recent_quarter().replace(year=2015)
                + timedelta(hours=horizon_days * 24)
            ]
        if not data["prices_forecast"].empty:
            data["prices_forecast"] = data["prices_forecast"].loc[
                data["prices_forecast"].index
                < time_utils.get_most_recent_quarter().replace(year=2015)
                + timedelta(hours=horizon_days * 24)
            ]
        if not data["weather_forecast"].empty:
            data["weather_forecast"] = data["weather_forecast"].loc[
                data["weather_forecast"].index
                < time_utils.get_most_recent_quarter().replace(year=2015)
                + timedelta(hours=horizon_days * 24)
            ]
        if not data["rev_cost_forecast"].empty:
            data["rev_cost_forecast"] = data["rev_cost_forecast"].loc[
                data["rev_cost_forecast"].index
                < time_utils.get_most_recent_quarter().replace(year=2015)
                + timedelta(hours=horizon_days * 24)
            ]

    # Making figures
    tools = ["box_zoom", "reset", "save"]
    power_fig = make_power_figure(
        data["power"],
        data["power_forecast"],
        data["power_schedule"],
        show_consumption_as_positive,
        shared_x_range,
        tools=tools,
    )
    prices_fig = make_prices_figure(
        data["prices"],
        data["prices_forecast"],
        shared_x_range,
        selected_market,
        tools=tools,
    )
    weather_fig = make_weather_figure(
        data["weather"],
        data["weather_forecast"],
        shared_x_range,
        selected_weather_sensor,
        tools=tools,
    )
    rev_cost_fig = make_revenues_costs_figure(
        data["rev_cost"],
        data["rev_cost_forecast"],
        show_consumption_as_positive,
        shared_x_range,
        selected_market,
        tools=tools,
    )

    # Separate a single legend and remove the others
    legend_fig = separate_legend(power_fig, orientation="horizontal")
    weather_fig.renderers.remove(weather_fig.legend[0])
    prices_fig.renderers.remove(prices_fig.legend[0])
    rev_cost_fig.renderers.remove(rev_cost_fig.legend[0])

    legend_script, legend_div = components(legend_fig)
    analytics_plots_script, analytics_plots_divs = components(
        (power_fig, weather_fig, prices_fig, rev_cost_fig)
    )

    return render_bvp_template(
        "views/analytics.html",
        legend_height=legend_fig.plot_height,
        legend_script=legend_script,
        legend_div=legend_div,
        analytics_plots_divs=[encode_utf8(div) for div in analytics_plots_divs],
        analytics_plots_script=analytics_plots_script,
        metrics=metrics,
        markets=markets,
        sensor_types=sensor_types,
        assets=assets,
        asset_group_names=asset_group_names,
        selected_market=selected_market,
        selected_resource=selected_resource,
        selected_sensor_type=selected_sensor_type,
        selected_sensor=selected_weather_sensor,
        asset_types=session_asset_types,
        showing_pure_consumption_data=showing_pure_consumption_data,
        showing_pure_production_data=showing_pure_production_data,
        show_consumption_as_positive=show_consumption_as_positive,
        forecast_horizons=time_utils.forecast_horizons_for(session["resolution"]),
        active_forecast_horizon=session["forecast_horizon"],
    )


@bvp_ui.route("/analytics_data/<content>/<content_type>", methods=["GET"])
@roles_accepted("admin", "Prosumer")
def analytics_data_view(content, content_type):
    """ Analytics view as above, but here we only download data.
    Content can be either metrics or raw.
    Content-type can be either CSV or JSON.
    """
    # if current_app.config.get("BVP_MODE", "") != "play":
    #    raise NotImplementedError("The analytics data download only works in play mode.")
    if content not in ("source", "metrics"):
        if content is None:
            content = "data"
        else:
            raise NotImplementedError("content can either be source or metrics.")
    if content_type not in ("csv", "json"):
        if content_type is None:
            content_type = "csv"
        else:
            raise NotImplementedError("content_type can either be csv or json.")

    time_utils.set_time_range_for_session()

    # Maybe move some of this stuff into get_data_and_metrics
    assets = get_assets()
    asset_groups = get_asset_group_queries(
        custom_additional_groups=[
            "renewables",
            "all Charge Points",
            "each Charge Point",
        ]
    )
    asset_group_names: List[str] = [
        group for group in asset_groups if asset_groups[group].count() > 0
    ]
    selected_resource = set_session_resource(assets, asset_group_names)
    selected_market = set_session_market(selected_resource)
    sensor_types = get_sensor_types(selected_resource)
    selected_sensor_type = set_session_sensor_type(sensor_types)

    # This is useful information - we might want to adapt the sign of the data and labels.
    showing_pure_consumption_data = all(
        [a.is_pure_consumer for a in Resource(session["resource"]).assets]
    )
    showing_pure_production_data = all(
        [a.is_pure_producer for a in Resource(session["resource"]).assets]
    )
    # Only show production positive if all assets are producers
    show_consumption_as_positive = False if showing_pure_production_data else True

    # Getting data and calculating metrics for them
    data, metrics, weather_type, selected_weather_sensor = get_data_and_metrics(
        show_consumption_as_positive,
        selected_market,
        selected_sensor_type,
        Resource(session["resource"]).assets,
    )

    hor = session["forecast_horizon"]
    rev_cost_header = (
        "costs/revenues" if show_consumption_as_positive else "revenues/costs"
    )
    if showing_pure_consumption_data:
        rev_cost_header = "costs"
    elif showing_pure_production_data:
        rev_cost_header = "revenues"
    source_headers = [
        "time",
        "power_data_label",
        "power",
        "power_forecast_label",
        f"power_forecast_{hor}",
        f"{weather_type}_label",
        f"{weather_type}",
        f"{weather_type}_forecast_label",
        f"{weather_type}_forecast_{hor}",
        "price_label",
        f"price_on_{selected_market.name}",
        "price_forecast_label",
        f"price_forecast_{hor}",
        f"{rev_cost_header}_label",
        rev_cost_header,
        f"{rev_cost_header}_forecast_label",
        f"{rev_cost_header}_forecast_{hor}",
    ]
    source_units = [
        "",
        "",
        "MW",
        "",
        "MW",
        "",
        selected_weather_sensor.unit,
        "",
        selected_weather_sensor.unit,
        "",
        selected_market.price_unit,
        "",
        selected_market.price_unit,
        "",
        selected_market.price_unit[:3],
        "",
        selected_market.price_unit[:3],
    ]
    filename_prefix = "%s_analytics" % selected_resource.name
    if content_type == "csv":
        str_io = io.StringIO()
        writer = csv.writer(str_io, dialect="excel")
        if content == "metrics":
            filename = "%s_metrics.csv" % filename_prefix
            writer.writerow(metrics.keys())
            writer.writerow(metrics.values())
        else:
            filename = "%s_source.csv" % filename_prefix
            writer.writerow(source_headers)
            writer.writerow(source_units)
            for dt in data["rev_cost"].index:
                row = [
                    dt,
                    data["power"].loc[dt].label
                    if "label" in data["power"].columns
                    else "Aggregated power data",
                    data["power"].loc[dt].y,
                    data["power_forecast"].loc[dt].label
                    if "label" in data["power_forecast"].columns
                    else "Aggregated power forecast data",
                    data["power_forecast"].loc[dt].yhat,
                    data["weather"].loc[dt].label
                    if "label" in data["weather"].columns
                    else f"Aggregated {weather_type} data",
                    data["weather"].loc[dt].y,
                    data["weather_forecast"].loc[dt].label
                    if "label" in data["weather_forecast"].columns
                    else f"Aggregated {weather_type} forecast data",
                    data["weather_forecast"].loc[dt].yhat,
                    data["prices"].loc[dt].label
                    if "label" in data["prices"].columns
                    else "Aggregated power data",
                    data["prices"].loc[dt].y,
                    data["prices_forecast"].loc[dt].label
                    if "label" in data["prices_forecast"].columns
                    else "Aggregated power data",
                    data["prices_forecast"].loc[dt].yhat,
                    data["rev_cost"].loc[dt].label
                    if "label" in data["rev_cost"].columns
                    else f"Aggregated {rev_cost_header} data",
                    data["rev_cost"].loc[dt].y,
                    data["rev_cost_forecast"].loc[dt].label
                    if "label" in data["rev_cost_forecast"].columns
                    else f"Aggregated {rev_cost_header} forecast data",
                    data["rev_cost_forecast"].loc[dt].yhat,
                ]
                writer.writerow(row)

        response = make_response(str_io.getvalue())
        response.headers["Content-Disposition"] = "attachment; filename=%s" % filename
        response.headers["Content-type"] = "text/csv"
    else:
        if content == "metrics":
            filename = "%s_metrics.json" % filename_prefix
            response = make_response(json.dumps(metrics))
        else:
            # Not quite done yet. I don't like how we treat forecasts in here yet. Not sure how to mention units.
            filename = "%s_source.json" % filename_prefix
            json_strings = []
            for key in data:
                json_strings.append(
                    f"\"{key}\":{data[key].to_json(orient='index', date_format='iso')}"
                )
            response = make_response("{%s}" % ",".join(json_strings))
        response.headers["Content-Disposition"] = "attachment; filename=%s" % filename
        response.headers["Content-type"] = "application/json"
    return response


def get_data_and_metrics(
    show_consumption_as_positive: bool, selected_market, selected_sensor_type, assets
) -> Tuple[Dict, Dict, str, WeatherSensor]:
    """Getting data and calculating metrics for them"""
    data = dict()
    metrics = dict()
    (
        data["power"],
        data["power_forecast"],
        data["power_schedule"],
        metrics,
    ) = get_power_data(show_consumption_as_positive, metrics)
    data["prices"], data["prices_forecast"], metrics = get_prices_data(
        metrics, selected_market
    )
    (
        data["weather"],
        data["weather_forecast"],
        weather_type,
        selected_sensor,
        metrics,
    ) = get_weather_data(assets, metrics, selected_sensor_type)
    # TODO: get rid of this hack, which we use because we mock forecast intervals in demo mode
    if current_app.config.get("BVP_MODE", "") == "demo":
        # In each case below, the error increases with the horizon towards a certain percentage of the point forecast
        horizon_entry = data["weather_forecast"]["horizon"].values[0]
        horizon = (
            horizon_entry[0].to_pytimedelta()[0]
            if isinstance(horizon_entry, list)
            else timedelta(days=1)
        )
        decay_factor = 1 - math.exp(-horizon / timedelta(hours=6))

        # Heuristic power confidence interval
        error_margin = 0.1 * decay_factor
        data["power_forecast"]["yhat_upper"] = data["power_forecast"]["yhat"] * (
            1 + error_margin
        )
        data["power_forecast"]["yhat_lower"] = data["power_forecast"]["yhat"] * (
            1 - error_margin
        )

        # Heuristic price confidence interval
        error_margin_upper = 0.6 * decay_factor
        error_margin_lower = 0.3 * decay_factor
        data["prices_forecast"]["yhat_upper"] = data["prices_forecast"]["yhat"] * (
            1 + error_margin_upper
        )
        data["prices_forecast"]["yhat_lower"] = data["prices_forecast"]["yhat"] * (
            1 - error_margin_lower
        )

        # Heuristic weather confidence interval
        if weather_type == "temperature":
            error_margin_upper = 0.1 * decay_factor
            error_margin_lower = error_margin_upper
        elif weather_type == "wind_speed":
            error_margin_upper = 1.5 * decay_factor
            error_margin_lower = 0.8 * decay_factor
        elif weather_type == "radiation":
            error_margin_upper = 1.8 * decay_factor
            error_margin_lower = 0.5 * decay_factor
        data["weather_forecast"]["yhat_upper"] = data["weather_forecast"]["yhat"] * (
            1 + error_margin_upper
        )
        data["weather_forecast"]["yhat_lower"] = data["weather_forecast"]["yhat"] * (
            1 - error_margin_lower
        )

    unit_factor = revenue_unit_factor("MWh", selected_market.unit)
    data["rev_cost"], data["rev_cost_forecast"], metrics = get_revenues_costs_data(
        data["power"],
        data["prices"],
        data["power_forecast"],
        data["prices_forecast"],
        metrics,
        unit_factor,
    )
    return data, metrics, weather_type, selected_sensor


def make_power_figure(
    data: pd.DataFrame,
    forecast_data: Optional[pd.DataFrame],
    schedule_data: Optional[pd.DataFrame],
    show_consumption_as_positive: bool,
    shared_x_range: Range1d,
    tools: List[str] = None,
) -> Figure:
    """Make a bokeh figure for power consumption or generation"""
    if show_consumption_as_positive:
        title = (
            "Electricity consumption of %s" % Resource(session["resource"]).display_name
        )
    else:
        title = (
            "Electricity production from %s"
            % Resource(session["resource"]).display_name
        )

    return create_graph(
        data,
        unit="MW",
        legend_location="top_right",
        legend_labels=("Actual", "Forecast")
        if schedule_data is None or schedule_data.yhat.isnull().all()
        else ("Actual", "Forecast", "Schedule"),
        forecasts=forecast_data,
        schedules=schedule_data,
        title=title,
        x_range=shared_x_range,
        x_label="Time (resolution of %s)"
        % time_utils.freq_label_to_human_readable_label(session["resolution"]),
        y_label="Power (in MW)",
        show_y_floats=True,
        tools=tools,
    )


def make_prices_figure(
    data: pd.DataFrame,
    forecast_data: Union[None, pd.DataFrame],
    shared_x_range: Range1d,
    selected_market: Market,
    tools: List[str] = None,
) -> Figure:
    """Make a bokeh figure for price data"""
    return create_graph(
        data,
        unit=selected_market.unit,
        legend_location="top_right",
        forecasts=forecast_data,
        title=f"Prices for {selected_market.display_name}",
        x_range=shared_x_range,
        x_label="Time (resolution of %s)"
        % time_utils.freq_label_to_human_readable_label(session["resolution"]),
        y_label="Price (in %s)" % selected_market.unit,
        show_y_floats=True,
        tools=tools,
    )


def make_weather_figure(
    data: pd.DataFrame,
    forecast_data: Union[None, pd.DataFrame],
    shared_x_range: Range1d,
    weather_sensor: WeatherSensor,
    tools: List[str] = None,
) -> Figure:
    """Make a bokeh figure for weather data"""
    # Todo: plot average temperature/total_radiation/wind_speed for asset groups, and update title accordingly
    if weather_sensor is None:
        return create_graph(pd.DataFrame())
    unit = weather_sensor.unit
    weather_axis_label = "%s (in %s)" % (
        humanize(weather_sensor.sensor_type.display_name),
        unit,
    )

    if Resource(session["resource"]).is_unique_asset:
        title = "%s at %s" % (
            humanize(weather_sensor.sensor_type.display_name),
            Resource(session["resource"]).display_name,
        )
    else:
        title = "%s" % humanize(weather_sensor.sensor_type.display_name)
    return create_graph(
        data,
        unit=unit,
        forecasts=forecast_data,
        title=title,
        x_range=shared_x_range,
        x_label="Time (resolution of %s)"
        % time_utils.freq_label_to_human_readable_label(session["resolution"]),
        y_label=weather_axis_label,
        legend_location="top_right",
        show_y_floats=True,
        tools=tools,
    )


def make_revenues_costs_figure(
    data: pd.DataFrame,
    forecast_data: pd.DataFrame,
    show_consumption_as_positive: bool,
    shared_x_range: Range1d,
    selected_market: Market,
    tools: List[str] = None,
) -> Figure:
    """Make a bokeh figure for revenues / costs data"""
    if show_consumption_as_positive:
        rev_cost_str = "Costs"
    else:
        rev_cost_str = "Revenues"

    return create_graph(
        data,
        unit=selected_market.unit[
            :3
        ],  # First three letters of a price unit give the currency (ISO 4217)
        legend_location="top_right",
        forecasts=forecast_data,
        title=f"{rev_cost_str} for {Resource(session['resource']).display_name} (on {selected_market.display_name})",
        x_range=shared_x_range,
        x_label="Time (resolution of %s)"
        % time_utils.freq_label_to_human_readable_label(session["resolution"]),
        y_label="%s (in %s)" % (rev_cost_str, selected_market.unit[:3]),
        show_y_floats=True,
        tools=tools,
    )


def revenue_unit_factor(quantity_unit: str, price_unit: str) -> float:
    market_quantity_unit = price_unit[
        4:
    ]  # First three letters of a price unit give the currency (ISO 4217), fourth character is "/"
    if quantity_unit == market_quantity_unit:
        return 1
    elif quantity_unit == "MWh" and price_unit[4:] == "kWh":
        return 1000
    else:
        raise NotImplementedError
