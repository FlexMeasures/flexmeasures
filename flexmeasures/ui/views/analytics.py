from typing import List, Optional, Union, Tuple, Dict
from datetime import datetime, timedelta
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
from pandas.tseries.frequencies import to_offset

from flexmeasures.data.models.markets import Market
from flexmeasures.data.models.weather import WeatherSensor
from flexmeasures.data.services.resources import (
    get_assets,
    get_asset_group_queries,
    get_markets,
    get_sensor_types,
    Resource,
)
from flexmeasures.data.queries.analytics import (
    get_power_data,
    get_prices_data,
    get_weather_data,
    get_revenues_costs_data,
)
from flexmeasures.utils import time_utils
from flexmeasures.utils.flexmeasures_inflection import humanize
from flexmeasures.ui.utils.view_utils import (
    render_flexmeasures_template,
    set_session_resource,
    set_session_market,
    set_session_sensor_type,
    set_individual_traces_for_session,
    set_time_range_for_session,
    ensure_timing_vars_are_set,
)
from flexmeasures.ui.utils.plotting_utils import create_graph, separate_legend
from flexmeasures.ui.views import flexmeasures_ui


@flexmeasures_ui.route("/analytics", methods=["GET", "POST"])
@roles_accepted("admin", "Prosumer")
def analytics_view():
    """Analytics view. Here, four plots (consumption/generation, weather, prices and a profit/loss calculation)
    and a table of metrics data are prepared. This view allows to select a resource name, from which a
    `models.Resource` object can be made. The resource name is kept in the session.
    Based on the resource, plots and table are labelled appropriately.
    """
    set_time_range_for_session()
    markets = get_markets()
    assets = get_assets(order_by_asset_attribute="display_name", order_direction="asc")
    asset_groups = get_asset_group_queries(
        custom_additional_groups=["renewables", "EVSE", "each Charge Point"]
    )
    asset_group_names: List[str] = [
        group for group in asset_groups if asset_groups[group].count() > 0
    ]
    selected_resource = set_session_resource(assets, asset_group_names)
    if selected_resource is None:
        raise Exception(
            "No assets exist yet, so the analytics view will not work. Please add an asset!"
        )

    selected_market = set_session_market(selected_resource)
    sensor_types = get_sensor_types(selected_resource)
    session_asset_types = selected_resource.unique_asset_types
    selected_sensor_type = set_session_sensor_type(sensor_types)
    set_individual_traces_for_session()
    view_shows_individual_traces = (
        session["showing_individual_traces_for"] in ("power", "schedules")
        and selected_resource.is_eligible_for_comparing_individual_traces()
    )

    query_window, resolution = ensure_timing_vars_are_set((None, None), None)

    # This is useful information - we might want to adapt the sign of the data and labels.
    showing_pure_consumption_data = all(
        [a.is_pure_consumer for a in selected_resource.assets]
    )
    showing_pure_production_data = all(
        [a.is_pure_producer for a in selected_resource.assets]
    )
    # Only show production positive if all assets are producers
    show_consumption_as_positive = False if showing_pure_production_data else True

    # ---- Get data

    data, metrics, weather_type, selected_weather_sensor = get_data_and_metrics(
        query_window,
        resolution,
        show_consumption_as_positive,
        session["showing_individual_traces_for"]
        if view_shows_individual_traces
        else "none",
        selected_resource,
        selected_market,
        selected_sensor_type,
        selected_resource.assets,
    )

    # TODO: get rid of these hacks, which we use because we mock the current year's data from 2015 data in demo mode
    # Our demo server uses 2015 data as if it's the current year's data. Here we mask future beliefs.
    if current_app.config.get("FLEXMEASURES_MODE", "") == "demo":
        data = filter_for_past_data(data)
        data = filter_forecasts_for_limited_time_window(data)

    # ---- Making figures

    # Set shared x range
    shared_x_range = Range1d(start=query_window[0], end=query_window[1])
    shared_x_range2 = Range1d(
        start=query_window[0], end=query_window[1]
    )  # only needed if we draw two legends (if individual traces are on)

    tools = ["box_zoom", "reset", "save"]
    power_fig = make_power_figure(
        selected_resource.display_name,
        data["power"],
        data["power_forecast"],
        data["power_schedule"],
        show_consumption_as_positive,
        shared_x_range,
        tools=tools,
    )
    rev_cost_fig = make_revenues_costs_figure(
        selected_resource.display_name,
        data["rev_cost"],
        data["rev_cost_forecast"],
        show_consumption_as_positive,
        shared_x_range,
        selected_market,
        tools=tools,
    )
    # the bottom plots need a separate x axis if they get their own legend (Bokeh complains otherwise)
    # this means in that in that corner case zooming will not work across all foour plots
    prices_fig = make_prices_figure(
        data["prices"],
        data["prices_forecast"],
        shared_x_range2 if view_shows_individual_traces else shared_x_range,
        selected_market,
        tools=tools,
    )
    weather_fig = make_weather_figure(
        selected_resource,
        data["weather"],
        data["weather_forecast"],
        shared_x_range2 if view_shows_individual_traces else shared_x_range,
        selected_weather_sensor,
        tools=tools,
    )

    # Separate a single legend and remove the others.
    # In case of individual traces, we need two legends.
    top_legend_fig = separate_legend(power_fig, orientation="horizontal")
    top_legend_script, top_legend_div = components(top_legend_fig)
    rev_cost_fig.renderers.remove(rev_cost_fig.legend[0])
    if view_shows_individual_traces:
        bottom_legend_fig = separate_legend(weather_fig, orientation="horizontal")
        prices_fig.renderers.remove(prices_fig.legend[0])
        bottom_legend_script, bottom_legend_div = components(bottom_legend_fig)
    else:
        prices_fig.renderers.remove(prices_fig.legend[0])
        weather_fig.renderers.remove(weather_fig.legend[0])
        bottom_legend_fig = bottom_legend_script = bottom_legend_div = None

    analytics_plots_script, analytics_plots_divs = components(
        (power_fig, rev_cost_fig, prices_fig, weather_fig)
    )

    return render_flexmeasures_template(
        "views/analytics.html",
        top_legend_height=top_legend_fig.plot_height,
        top_legend_script=top_legend_script,
        top_legend_div=top_legend_div,
        bottom_legend_height=0
        if bottom_legend_fig is None
        else bottom_legend_fig.plot_height,
        bottom_legend_script=bottom_legend_script,
        bottom_legend_div=bottom_legend_div,
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
        showing_individual_traces_for=session["showing_individual_traces_for"],
        offer_showing_individual_traces=selected_resource.is_eligible_for_comparing_individual_traces(),
        forecast_horizons=time_utils.forecast_horizons_for(session["resolution"]),
        active_forecast_horizon=session["forecast_horizon"],
    )


@flexmeasures_ui.route("/analytics_data/<content>/<content_type>", methods=["GET"])
@roles_accepted("admin", "Prosumer")
def analytics_data_view(content, content_type):
    """Analytics view as above, but here we only download data.
    Content can be either source or metrics.
    Content-type can be either CSV or JSON.
    """
    # if current_app.config.get("FLEXMEASURES_MODE", "") != "play":
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
    assets = get_assets(order_by_asset_attribute="display_name", order_direction="asc")
    asset_groups = get_asset_group_queries(
        custom_additional_groups=["renewables", "EVSE", "each Charge Point"]
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
        [a.is_pure_consumer for a in selected_resource.assets]
    )
    showing_pure_production_data = all(
        [a.is_pure_producer for a in selected_resource.assets]
    )
    # Only show production positive if all assets are producers
    show_consumption_as_positive = False if showing_pure_production_data else True

    # Getting data and calculating metrics for them
    query_window, resolution = ensure_timing_vars_are_set((None, None), None)
    data, metrics, weather_type, selected_weather_sensor = get_data_and_metrics(
        query_window,
        resolution,
        show_consumption_as_positive,
        "none",
        selected_resource,
        selected_market,
        selected_sensor_type,
        selected_resource.assets,
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
                    data["power"].loc[dt]["event_value"],
                    data["power_forecast"].loc[dt].label
                    if "label" in data["power_forecast"].columns
                    else "Aggregated power forecast data",
                    data["power_forecast"].loc[dt]["event_value"],
                    data["weather"].loc[dt].label
                    if "label" in data["weather"].columns
                    else f"Aggregated {weather_type} data",
                    data["weather"].loc[dt]["event_value"],
                    data["weather_forecast"].loc[dt].label
                    if "label" in data["weather_forecast"].columns
                    else f"Aggregated {weather_type} forecast data",
                    data["weather_forecast"].loc[dt]["event_value"],
                    data["prices"].loc[dt].label
                    if "label" in data["prices"].columns
                    else "Aggregated power data",
                    data["prices"].loc[dt]["event_value"],
                    data["prices_forecast"].loc[dt].label
                    if "label" in data["prices_forecast"].columns
                    else "Aggregated power data",
                    data["prices_forecast"].loc[dt]["event_value"],
                    data["rev_cost"].loc[dt].label
                    if "label" in data["rev_cost"].columns
                    else f"Aggregated {rev_cost_header} data",
                    data["rev_cost"].loc[dt]["event_value"],
                    data["rev_cost_forecast"].loc[dt].label
                    if "label" in data["rev_cost_forecast"].columns
                    else f"Aggregated {rev_cost_header} forecast data",
                    data["rev_cost_forecast"].loc[dt]["event_value"],
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
    query_window: Tuple[datetime, datetime],
    resolution: str,
    show_consumption_as_positive: bool,
    showing_individual_traces_for: str,
    selected_resource: Resource,
    selected_market,
    selected_sensor_type,
    assets,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, float], str, WeatherSensor]:
    """Getting data and calculating metrics for them"""
    data: Dict[str, pd.DataFrame] = dict()
    forecast_horizon = pd.to_timedelta(session["forecast_horizon"])
    metrics: dict = dict()
    (
        data["power"],
        data["power_forecast"],
        data["power_schedule"],
        metrics,
    ) = get_power_data(
        selected_resource,
        show_consumption_as_positive,
        showing_individual_traces_for,
        metrics,
        query_window,
        resolution,
        forecast_horizon,
    )
    data["prices"], data["prices_forecast"], metrics = get_prices_data(
        metrics,
        selected_market,
        query_window,
        resolution,
        forecast_horizon,
    )
    (
        data["weather"],
        data["weather_forecast"],
        weather_type,
        selected_sensor,
        metrics,
    ) = get_weather_data(
        assets,
        metrics,
        selected_sensor_type,
        query_window,
        resolution,
        forecast_horizon,
    )
    # TODO: get rid of this hack, which we use because we mock forecast intervals in demo mode
    if current_app.config.get("FLEXMEASURES_MODE", "") == "demo":
        # In each case below, the error increases with the horizon towards a certain percentage of the point forecast
        horizon = pd.to_timedelta(to_offset(session.get("forecast_horizon", "1d")))
        decay_factor = 1 - math.exp(-horizon / timedelta(hours=6))

        # Heuristic power confidence interval
        error_margin = 0.1 * decay_factor
        data["power_forecast"]["yhat_upper"] = data["power_forecast"]["event_value"] * (
            1 + error_margin
        )
        data["power_forecast"]["yhat_lower"] = data["power_forecast"]["event_value"] * (
            1 - error_margin
        )

        # Heuristic price confidence interval
        error_margin_upper = 0.6 * decay_factor
        error_margin_lower = 0.3 * decay_factor
        data["prices_forecast"]["yhat_upper"] = data["prices_forecast"][
            "event_value"
        ] * (1 + error_margin_upper)
        data["prices_forecast"]["yhat_lower"] = data["prices_forecast"][
            "event_value"
        ] * (1 - error_margin_lower)

        # Heuristic weather confidence interval
        if weather_type == "temperature":
            error_margin_upper = 0.7 * decay_factor
            error_margin_lower = error_margin_upper
        elif weather_type == "wind_speed":
            error_margin_upper = 1.5 * decay_factor
            error_margin_lower = 0.8 * decay_factor
        elif weather_type == "radiation":
            error_margin_upper = 1.8 * decay_factor
            error_margin_lower = 0.5 * decay_factor
        if data["weather_forecast"].empty:
            data["weather_forecast"] = data["weather"].copy()
            data["weather_forecast"]["event_value"] *= 1.1
        data["weather_forecast"]["yhat_upper"] = data["weather_forecast"][
            "event_value"
        ] * (1 + error_margin_upper)
        data["weather_forecast"]["yhat_lower"] = data["weather_forecast"][
            "event_value"
        ] * (1 - error_margin_lower)

    unit_factor = revenue_unit_factor("MWh", selected_market.unit)
    data["rev_cost"], data["rev_cost_forecast"], metrics = get_revenues_costs_data(
        data["power"],
        data["prices"],
        data["power_forecast"],
        data["prices_forecast"],
        metrics,
        unit_factor,
        resolution,
        showing_individual_traces_for in ("power", "schedules"),
    )
    return data, metrics, weather_type, selected_sensor


def filter_for_past_data(data):
    """ Make sure we only show past data, useful for demo mode """
    most_recent_quarter = time_utils.get_most_recent_quarter()

    if not data["power"].empty:
        data["power"] = data["power"].loc[
            data["power"].index.get_level_values("event_start") < most_recent_quarter
        ]
    if not data["prices"].empty:
        data["prices"] = data["prices"].loc[
            data["prices"].index < most_recent_quarter + timedelta(hours=24)
        ]  # keep tomorrow's prices
    if not data["weather"].empty:
        data["weather"] = data["weather"].loc[
            data["weather"].index < most_recent_quarter
        ]
    if not data["rev_cost"].empty:
        data["rev_cost"] = data["rev_cost"].loc[
            data["rev_cost"].index.get_level_values("event_start") < most_recent_quarter
        ]
    return data


def filter_forecasts_for_limited_time_window(data):
    """ Show forecasts only up to a limited horizon """
    most_recent_quarter = time_utils.get_most_recent_quarter()
    horizon_days = 10  # keep a 10 day forecast
    max_forecast_datetime = most_recent_quarter + timedelta(hours=horizon_days * 24)
    if not data["power_forecast"].empty:
        data["power_forecast"] = data["power_forecast"].loc[
            data["power_forecast"].index < max_forecast_datetime
        ]
    if not data["prices_forecast"].empty:
        data["prices_forecast"] = data["prices_forecast"].loc[
            data["prices_forecast"].index < max_forecast_datetime
        ]
    if not data["weather_forecast"].empty:
        data["weather_forecast"] = data["weather_forecast"].loc[
            data["weather_forecast"].index < max_forecast_datetime
        ]
    if not data["rev_cost_forecast"].empty:
        data["rev_cost_forecast"] = data["rev_cost_forecast"].loc[
            data["rev_cost_forecast"].index < max_forecast_datetime
        ]
    return data


def make_power_figure(
    resource_display_name: str,
    data: pd.DataFrame,
    forecast_data: Optional[pd.DataFrame],
    schedule_data: Optional[pd.DataFrame],
    show_consumption_as_positive: bool,
    shared_x_range: Range1d,
    tools: List[str] = None,
    sizing_mode="scale_width",
) -> Figure:
    """Make a bokeh figure for power consumption or generation"""
    if show_consumption_as_positive:
        title = "Electricity consumption of %s" % resource_display_name
    else:
        title = "Electricity production from %s" % resource_display_name
    if data.empty:
        title = title.replace("Electricity", "Prognosed")

    return create_graph(
        data,
        unit="MW",
        legend_location="top_right",
        legend_labels=("Actual", "Forecast", None)
        if schedule_data is None or schedule_data["event_value"].isnull().all()
        else ("Actual", "Forecast", "Schedule"),
        forecasts=forecast_data,
        schedules=schedule_data,
        title=title,
        x_range=shared_x_range,
        x_label="Time (resolution of %s)"
        % determine_resolution(data, forecast_data, schedule_data),
        y_label="Power (in MW)",
        show_y_floats=True,
        tools=tools,
        sizing_mode=sizing_mode,
    )


def make_prices_figure(
    data: pd.DataFrame,
    forecast_data: Union[None, pd.DataFrame],
    shared_x_range: Range1d,
    selected_market: Market,
    tools: List[str] = None,
    sizing_mode="scale_width",
) -> Figure:
    """Make a bokeh figure for price data"""
    return create_graph(
        data,
        unit=selected_market.unit,
        legend_location="top_right",
        forecasts=forecast_data,
        title=f"Prices for {selected_market.display_name}",
        x_range=shared_x_range,
        x_label="Time (resolution of %s)" % determine_resolution(data, forecast_data),
        y_label="Price (in %s)" % selected_market.unit,
        show_y_floats=True,
        tools=tools,
        sizing_mode=sizing_mode,
    )


def make_weather_figure(
    selected_resource: Resource,
    data: pd.DataFrame,
    forecast_data: Union[None, pd.DataFrame],
    shared_x_range: Range1d,
    weather_sensor: WeatherSensor,
    tools: List[str] = None,
    sizing_mode="scale_width",
) -> Figure:
    """Make a bokeh figure for weather data"""
    # Todo: plot average temperature/total_radiation/wind_speed for asset groups, and update title accordingly
    if weather_sensor is None:
        return create_graph(
            pd.DataFrame(columns=["event_value"]),
            title="Weather plot (no relevant weather sensor found)",
        )
    unit = weather_sensor.unit
    weather_axis_label = "%s (in %s)" % (
        humanize(weather_sensor.sensor_type.display_name),
        unit,
    )

    if selected_resource.is_unique_asset:
        title = "%s at %s" % (
            humanize(weather_sensor.sensor_type.display_name),
            selected_resource.display_name,
        )
    else:
        title = "%s" % humanize(weather_sensor.sensor_type.display_name)
    return create_graph(
        data,
        unit=unit,
        forecasts=forecast_data,
        title=title,
        x_range=shared_x_range,
        x_label="Time (resolution of %s)" % determine_resolution(data, forecast_data),
        y_label=weather_axis_label,
        legend_location="top_right",
        show_y_floats=True,
        tools=tools,
        sizing_mode=sizing_mode,
    )


def make_revenues_costs_figure(
    resource_display_name: str,
    data: pd.DataFrame,
    forecast_data: pd.DataFrame,
    show_consumption_as_positive: bool,
    shared_x_range: Range1d,
    selected_market: Market,
    tools: List[str] = None,
    sizing_mode="scale_width",
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
        title=f"{rev_cost_str} for {resource_display_name} (on {selected_market.display_name})",
        x_range=shared_x_range,
        x_label="Time (resolution of %s)" % determine_resolution(data, forecast_data),
        y_label="%s (in %s)" % (rev_cost_str, selected_market.unit[:3]),
        show_y_floats=True,
        tools=tools,
        sizing_mode=sizing_mode,
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


def determine_resolution(
    data: pd.DataFrame,
    forecasts: Optional[pd.DataFrame] = None,
    schedules: Optional[pd.DataFrame] = None,
) -> str:
    """
    Determine the resolution to be displayed under the plot.
    We try to get it from the DataFrame's meta data, or guess from the actual data.
    Lastly, we try the session.
    If nothing can be found this way, the resulting string is "?"
    """

    def determine_resolution_for(df: pd.DataFrame) -> str:
        if hasattr(df, "event_resolution"):  # BeliefsDataFrame
            freq_str = time_utils.timedelta_to_pandas_freq_str(df.event_resolution)
        elif hasattr(df.index, "freqstr") and df.index.freqstr is not None:
            freq_str = data.index.freqstr
        elif hasattr(df.index, "inferred_freq") and df.index.inferred_freq is not None:
            freq_str = df.index.inferred_freq
        elif "resolution" in session:
            freq_str = session["resolution"]
        else:
            return "?"
        return time_utils.freq_label_to_human_readable_label(freq_str)

    resolution = determine_resolution_for(data)
    if resolution == "?" and forecasts is not None:
        resolution = determine_resolution_for(forecasts)
    if resolution == "?" and schedules is not None:
        resolution = determine_resolution_for(schedules)
    return resolution
