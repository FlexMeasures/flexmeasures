from flask import request, session
import pandas as pd
import numpy as np
from inflection import pluralize, titleize
from bokeh.embed import components
from bokeh.palettes import brewer as color_palette  # pycharm cannot see this, ignore the warning (Alt-Enter)

import models
from utils import time_utils
from utils.data_access import get_assets, get_data_for_assets, Resource
import plotting
from views import bvp_views
from views.utils import render_bvp_template, check_prosumer_mock, filter_mock_prosumer_assets


# Portfolio view
@bvp_views.route('/portfolio', methods=['GET', 'POST'])
def portfolio_view():
    time_utils.set_time_range_for_session()

    assets = get_assets()
    if check_prosumer_mock():
        assets = filter_mock_prosumer_assets(assets)

    # get data for summaries over the selected period
    production_per_asset = dict.fromkeys([a.name for a in assets])
    consumption_per_asset = dict.fromkeys([a.name for a in assets])
    profit_loss_per_asset = dict.fromkeys([a.name for a in assets])

    represented_asset_types = {}
    production_per_asset_type = {}
    consumption_per_asset_type = {}
    profit_loss_per_asset_type = {}

    prices_data = get_data_for_assets(["epex_da"])

    load_hour_factor = time_utils.resolution_to_hour_factor(session["resolution"])

    for asset in assets:
        load_data = get_data_for_assets([asset.name])
        profit_loss_per_asset[asset.name] = pd.Series(load_data.y * load_hour_factor * prices_data.y,
                                                      index=load_data.index).sum()
        if asset.is_pure_consumer:
            production_per_asset[asset.name] = 0
            consumption_per_asset[asset.name] = -1 * pd.Series(load_data.y).sum() * load_hour_factor
        else:
            production_per_asset[asset.name] = pd.Series(load_data.y).sum() * load_hour_factor
            consumption_per_asset[asset.name] = 0
        neat_asset_type_name = titleize(asset.asset_type_name)
        if neat_asset_type_name not in production_per_asset_type:
            represented_asset_types[neat_asset_type_name] = asset.asset_type
            production_per_asset_type[neat_asset_type_name] = 0.
            consumption_per_asset_type[neat_asset_type_name] = 0.
            profit_loss_per_asset_type[neat_asset_type_name] = 0.
        production_per_asset_type[neat_asset_type_name] += production_per_asset[asset.name]
        consumption_per_asset_type[neat_asset_type_name] += consumption_per_asset[asset.name]
        profit_loss_per_asset_type[neat_asset_type_name] += profit_loss_per_asset[asset.name]

    # get data for stacked plot for the selected period

    def only_positive(df: pd.DataFrame) -> None:
        df[df < 0] = 0

    def only_negative_abs(df: pd.DataFrame) -> None:
        # If this functions fails, a possible solution may be to stack the dataframe before
        # checking for negative values (unstacking afterwards).
        # df = df.stack()
        df[df > 0] = 0
        # df = df.unstack()
        df[:] = df * -1

    def data_or_zeroes(df: pd.DataFrame) -> pd.DataFrame:
        if df is None:
            return pd.DataFrame(index=pd.date_range(start=session["start_time"], end=session["end_time"],
                                                    freq=session["resolution"]),
                                columns=["y"]).fillna(0)
        else:
            return df

    def stacked(df: pd.DataFrame) -> pd.DataFrame:
        """Stack columns of df cumulatively, include bottom"""
        df_top = df.cumsum(axis=1)
        df_bottom = df_top.shift(axis=1).fillna(0)[::-1]
        df_stack = pd.concat([df_bottom, df_top], ignore_index=True)
        return df_stack

    default_stack_side = "production"
    if session.get("prosumer_mock", "0") in ("buildings", "vehicles"):
        default_stack_side = "consumption"
    show_stacked = request.values.get("show_stacked", default_stack_side)
    if show_stacked == "production":
        show_summed = "consumption"
        stack_types = [t.name for t in represented_asset_types.values() if t.is_producer is True]
        sum_assets = [a.name for a in assets if a.asset_type.is_consumer is True]
        plot_label = "Stacked Production vs aggregated Consumption"
        stacked_value_mask = only_positive
        summed_value_mask = only_negative_abs
    else:
        show_summed = "production"
        stack_types = [t.name for t in represented_asset_types.values() if t.is_consumer is True]
        sum_assets = [a.name for a in assets if a.asset_type.is_producer is True]
        plot_label = "Stacked Consumption vs aggregated Production"
        stacked_value_mask = only_negative_abs
        summed_value_mask = only_positive

    df_sum = get_data_for_assets(sum_assets)
    if df_sum is not None:
        df_sum = df_sum.loc[:, ['y']]  # only get the y data
    df_sum = data_or_zeroes(df_sum)
    summed_value_mask(df_sum)
    hover = plotting.create_hover_tool("MW", session.get("resolution"))
    fig = plotting.create_graph(df_sum.y,
                                title=plot_label,
                                x_label="Time (sampled by %s)"
                                        % time_utils.freq_label_to_human_readable_label(session["resolution"]),
                                y_label="%s (in MW)" % plot_label,
                                legend=titleize(show_summed),
                                hover_tool=hover)
    fig.plot_height = 450
    fig.plot_width = 750
    fig.sizing_mode = "fixed"

    df_stacked_data = pd.DataFrame(index=df_sum.index, columns=stack_types)
    for st in stack_types:
        df_stacked_data[st] = Resource(pluralize(st)).get_data().loc[:, ['y']]  # only get the y data
    stacked_value_mask(df_stacked_data)
    df_stacked_data = data_or_zeroes(df_stacked_data)
    df_stacked_areas = stacked(df_stacked_data)

    num_areas = df_stacked_areas.shape[1]
    if num_areas <= 2:
        colors = ['#99d594', '#dddd9d']
    else:
        colors = color_palette['Spectral'][num_areas]
    x_points = np.hstack((df_stacked_data.index[::-1], df_stacked_data.index))

    fig.grid.minor_grid_line_color = '#eeeeee'

    for a, area in enumerate(df_stacked_areas):
        fig.patch(x_points, df_stacked_areas[area].values,
                  color=colors[a], alpha=0.8, line_color=None, legend=titleize(df_stacked_data.columns[a]))

    portfolio_plot_script, portfolio_plot_div = components(fig)

    return render_bvp_template("portfolio.html", prosumer_mock=session.get("prosumer_mock", "0"),
                               assets=assets,
                               asset_types=represented_asset_types,
                               production_per_asset=production_per_asset,
                               consumption_per_asset=consumption_per_asset,
                               profit_loss_per_asset=profit_loss_per_asset,
                               production_per_asset_type=production_per_asset_type,
                               consumption_per_asset_type=consumption_per_asset_type,
                               profit_loss_per_asset_type=profit_loss_per_asset_type,
                               sum_production=sum(production_per_asset_type.values()),
                               sum_consumption=sum(consumption_per_asset_type.values()),
                               sum_profit_loss=sum(profit_loss_per_asset_type.values()),
                               portfolio_plot_script=portfolio_plot_script,
                               portfolio_plot_div=portfolio_plot_div,
                               alt_stacking=show_summed)
