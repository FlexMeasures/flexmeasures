from typing import List, Union, Tuple, Dict
from datetime import timedelta
import io
import csv
import json

import pandas as pd
from flask import session, current_app, make_response
from flask_security import roles_accepted
from bokeh.plotting import Figure
from bokeh.embed import components
from bokeh.util.string import encode_utf8
from bokeh.models import Range1d
from inflection import titleize, humanize

from bvp.ui.views import bvp_ui
from bvp.utils import time_utils
from bvp.data.models.markets import Market
from bvp.data.models.weather import WeatherSensor
from bvp.data.services.resources import (
    get_assets,
    get_asset_groups,
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
from bvp.ui.utils.view_utils import (
    render_bvp_template,
    set_session_resource,
    set_session_market,
    set_session_sensor_type,
)
from bvp.ui.utils.plotting_utils import create_graph, separate_legend


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
    asset_groups = get_asset_groups()
    groups_with_assets: List[str] = [
        group for group in asset_groups if asset_groups[group].count() > 0
    ]
    selected_resource = set_session_resource(assets, groups_with_assets)
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

    data, metrics, weather_type, selected_weather_sensor = get_data_and_metrics(
        showing_pure_consumption_data,
        selected_market,
        selected_sensor_type,
        Resource(session["resource"]).assets,
    )

    # TODO: get rid of this hack, which we use because we mock 2015 data in static mode
    if current_app.config.get("BVP_MODE", "") == "demo":
        if not data["power"].empty:
            data["power"] = data["power"].loc[
                data["power"].index
                < time_utils.get_most_recent_quarter().replace(year=2015)
            ]
        if not data["prices"].empty:
            data["prices"] = data["prices"].loc[
                data["prices"].index
                < time_utils.get_most_recent_quarter().replace(year=2015)
            ]
        if not data["weather"].empty:
            data["weather"] = data["weather"].loc[
                data["weather"].index
                < time_utils.get_most_recent_quarter().replace(year=2015)
                + timedelta(hours=24)
            ]
        if not data["rev_cost"].empty:
            data["rev_cost"] = data["rev_cost"].loc[
                data["rev_cost"].index
                < time_utils.get_most_recent_quarter().replace(year=2015)
            ]

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

    # Making figures
    tools = ["box_zoom", "reset", "save"]
    power_fig = make_power_figure(
        data["power"],
        data["power_forecast"],
        showing_pure_consumption_data,
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
        showing_pure_consumption_data,
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
        asset_groups=list(
            zip(groups_with_assets, [titleize(gwa) for gwa in groups_with_assets])
        ),
        selected_market=selected_market,
        selected_resource=selected_resource,
        selected_sensor_type=selected_sensor_type,
        selected_sensor=selected_weather_sensor,
        asset_types=session_asset_types,
        showing_pure_consumption_data=showing_pure_consumption_data,
        showing_pure_production_data=showing_pure_production_data,
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
    asset_groups = get_asset_groups()
    groups_with_assets: List[str] = [
        group for group in asset_groups if asset_groups[group].count() > 0
    ]
    selected_resource = set_session_resource(assets, groups_with_assets)
    selected_market = set_session_market(selected_resource)
    sensor_types = get_sensor_types(selected_resource)
    selected_sensor_type = set_session_sensor_type(sensor_types)

    # This is useful information - we might want to adapt the sign of the data and labels.
    showing_pure_consumption_data = all(
        [a.is_pure_consumer for a in Resource(session["resource"]).assets]
    )

    # Getting data and calculating metrics for them
    data, metrics, weather_type, selected_weather_sensor = get_data_and_metrics(
        showing_pure_consumption_data,
        selected_market,
        selected_sensor_type,
        Resource(session["resource"]).assets,
    )

    hor = session["forecast_horizon"]
    source_headers = [
        "time",
        "power",
        f"power_forecast_{hor}",
        f"{weather_type}",
        f"{weather_type}_forecast_{hor}",
        f"price",
        f"price_forecast_{hor}",
        "revenues_costs",
        f"revenues_costs_forecast_{hor}",
    ]
    source_units = [
        "",
        "MW",
        "MW",
        selected_weather_sensor.unit,
        selected_weather_sensor.unit,
        selected_market.price_unit,
        selected_market.price_unit,
        selected_market.price_unit[:3],
        selected_market.price_unit[:3],
    ]
    if content_type == "csv":
        str_io = io.StringIO()
        writer = csv.writer(str_io, dialect="excel")
        if content == "metrics":
            filename = "%s_analytics_metrics.csv" % selected_resource.name
            writer.writerow(metrics.keys())
            writer.writerow(metrics.values())
        else:
            filename = "%s_analytics_source.csv" % selected_resource.name
            writer.writerow(source_headers)
            writer.writerow(source_units)
            for dt in data["rev_cost"].index:
                writer.writerow(
                    [
                        dt,
                        data["power"].loc[dt].y,
                        data["power_forecast"].loc[dt].yhat,
                        data["weather"].loc[dt].y,
                        data["weather_forecast"].loc[dt].yhat,
                        data["prices"].loc[dt].y,
                        data["prices_forecast"].loc[dt].yhat,
                        data["rev_cost"].loc[dt].y,
                        data["rev_cost_forecast"].loc[dt].yhat,
                    ]
                )

        response = make_response(str_io.getvalue())
        response.headers["Content-Disposition"] = "attachment; filename=%s" % filename
        response.headers["Content-type"] = "text/csv"
    else:
        if content == "metrics":
            filename = "%s_analytics_metrics.json" % selected_resource.name
            response = make_response(json.dumps(metrics))
        else:
            # Not quite done yet. I don't like how we treat forecasts in here yet. Not sure how to mention units.
            filename = "%s_analytics_source.json" % selected_resource.name
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
    showing_pure_consumption_data, selected_market, selected_sensor_type, assets
) -> Tuple[Dict, Dict, str, WeatherSensor]:
    """Getting data and calculating metrics for them"""
    data = dict()
    metrics = dict()
    data["power"], data["power_forecast"], metrics = get_power_data(
        showing_pure_consumption_data, metrics
    )
    data["prices"], data["prices_forecast"], metrics = get_prices_data(
        metrics, selected_market
    )
    data["weather"], data[
        "weather_forecast"
    ], weather_type, selected_sensor, metrics = get_weather_data(
        assets, metrics, selected_sensor_type
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
    forecast_data: Union[None, pd.DataFrame],
    showing_pure_consumption_data: bool,
    shared_x_range: Range1d,
    tools: List[str] = None,
) -> Figure:
    """Make a bokeh figure for power consumption or generation"""
    if showing_pure_consumption_data:
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
        forecasts=forecast_data,
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
        title="%s %s prices"
        % (selected_market.display_name, selected_market.market_type.display_name),
        x_range=shared_x_range,
        x_label="Time (resolution of %s)"
        % time_utils.freq_label_to_human_readable_label(session["resolution"]),
        y_label="Prices (in %s)" % selected_market.unit,
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
    showing_pure_consumption_data: bool,
    shared_x_range: Range1d,
    selected_market: Market,
    tools: List[str] = None,
) -> Figure:
    """Make a bokeh figure for revenues / costs data"""
    if showing_pure_consumption_data:
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
        title="%s for %s (on %s %s)"
        % (
            rev_cost_str,
            Resource(session["resource"]).display_name,
            selected_market.display_name,
            selected_market.market_type.display_name,
        ),
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
