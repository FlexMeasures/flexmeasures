from datetime import timedelta

from flask import request, session
from flask_security import roles_accepted
from flask_security.core import current_user
import pandas as pd
import numpy as np
from inflection import pluralize, titleize
from bokeh.layouts import gridplot
from bokeh.embed import components
import bokeh.palettes as palettes

from bvp.utils import time_utils
from bvp.utils.data_access import get_assets, get_data_for_assets, Resource
import bvp.utils.plotting_utils as plotting
from bvp.views import bvp_views
from bvp.utils.view_utils import render_bvp_template


# Portfolio view
@bvp_views.route('/portfolio', methods=['GET', 'POST'])
@roles_accepted("admin", "asset-owner")
def portfolio_view():
    """ Portfolio view.
    By default, this page shows live results (production, consumption and market data) from the user's portfolio.
    Time windows for which the platform has identified upcoming balancing opportunities are highlighted.
    The page can also be used to navigate historical results.
    """
    time_utils.set_time_range_for_session()
    start = session.get("start_time")
    end = session.get("end_time")
    resolution = session.get("resolution")

    assets = get_assets()

    production_per_asset = dict.fromkeys([a.name for a in assets])
    consumption_per_asset = dict.fromkeys([a.name for a in assets])
    profit_loss_energy_per_asset = dict.fromkeys([a.name for a in assets])
    curtailment_per_asset = dict.fromkeys([a.name for a in assets])
    shifting_per_asset = dict.fromkeys([a.name for a in assets])
    profit_loss_flexibility_per_asset = dict.fromkeys([a.name for a in assets])

    production_per_asset_type = {}
    consumption_per_asset_type = {}
    profit_loss_energy_per_asset_type = {}
    curtailment_per_asset_type = {}
    shifting_per_asset_type = {}
    profit_loss_flexibility_per_asset_type = {}

    represented_asset_types = {}

    prices_data = get_data_for_assets(["epex_da"], start=start, end=end, resolution=resolution)

    load_hour_factor = time_utils.resolution_to_hour_factor(resolution)

    for asset in assets:
        power_data = get_data_for_assets([asset.name], start=start, end=end, resolution=resolution)
        profit_loss_energy_per_asset[asset.name] = pd.Series(power_data.y * load_hour_factor * prices_data.y,
                                                             index=power_data.index).sum()
        if asset.is_pure_consumer:
            production_per_asset[asset.name] = 0
            consumption_per_asset[asset.name] = -1 * pd.Series(power_data.y).sum() * load_hour_factor
        else:
            production_per_asset[asset.name] = pd.Series(power_data.y).sum() * load_hour_factor
            consumption_per_asset[asset.name] = 0
        neat_asset_type_name = titleize(asset.asset_type_name)
        if neat_asset_type_name not in production_per_asset_type:
            represented_asset_types[neat_asset_type_name] = asset.asset_type
            production_per_asset_type[neat_asset_type_name] = 0.
            consumption_per_asset_type[neat_asset_type_name] = 0.
            profit_loss_energy_per_asset_type[neat_asset_type_name] = 0.
            curtailment_per_asset_type[neat_asset_type_name] = 0.
            shifting_per_asset_type[neat_asset_type_name] = 0.
            profit_loss_flexibility_per_asset_type[neat_asset_type_name] = 0.
        production_per_asset_type[neat_asset_type_name] += production_per_asset[asset.name]
        consumption_per_asset_type[neat_asset_type_name] += consumption_per_asset[asset.name]
        profit_loss_energy_per_asset_type[neat_asset_type_name] += profit_loss_energy_per_asset[asset.name]

        # flexibility numbers are mocked for now
        curtailment_per_asset[asset.name] = 0
        shifting_per_asset[asset.name] = 0
        profit_loss_flexibility_per_asset[asset.name] = 0
        if asset.name == "48_r":
            shifting_per_asset[asset.name] = 1.1
            profit_loss_flexibility_per_asset[asset.name] = 76000
        if asset.name == "hw-onshore":
            curtailment_per_asset[asset.name] = 1.3
            profit_loss_flexibility_per_asset[asset.name] = 84000
        curtailment_per_asset_type[neat_asset_type_name] += curtailment_per_asset[asset.name]
        shifting_per_asset_type[neat_asset_type_name] += shifting_per_asset[asset.name]
        profit_loss_flexibility_per_asset_type[neat_asset_type_name] += profit_loss_flexibility_per_asset[asset.name]

    # get data for stacked plot for the selected period

    def only_positive(df: pd.DataFrame) -> None:
        # noinspection PyTypeChecker
        df[df < 0] = 0

    # noinspection PyTypeChecker
    def only_negative_abs(df: pd.DataFrame) -> None:
        # If this functions fails, a possible solution may be to stack the dataframe before
        # checking for negative values (unstacking afterwards).
        # df = df.stack()
        df[df > 0] = 0
        # df = df.unstack()
        df[:] = df * -1

    def data_or_zeroes(df: pd.DataFrame) -> pd.DataFrame:
        if df is None:
            return pd.DataFrame(index=pd.date_range(start=start, end=end, freq=resolution),
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
    if "building" in current_user.email or "charging" in current_user.email:
        default_stack_side = "consumption"
    show_stacked = request.values.get("show_stacked", default_stack_side)
    if show_stacked == "production":
        show_summed = "consumption"
        stack_types = [t.name for t in represented_asset_types.values() if t.is_producer is True]
        sum_assets = [a.name for a in assets if a.asset_type.is_consumer is True]
        plot_label = "Stacked production vs aggregated consumption"
        stacked_value_mask = only_positive
        summed_value_mask = only_negative_abs
    else:
        show_summed = "production"
        stack_types = [t.name for t in represented_asset_types.values() if t.is_consumer is True]
        sum_assets = [a.name for a in assets if a.asset_type.is_producer is True]
        plot_label = "Stacked consumption vs aggregated production"
        stacked_value_mask = only_negative_abs
        summed_value_mask = only_positive

    df_sum = get_data_for_assets(sum_assets, start=start, end=end, resolution=resolution)
    if df_sum is not None:
        df_sum = df_sum.loc[:, ['y']]  # only get the y data
    df_sum = data_or_zeroes(df_sum)
    summed_value_mask(df_sum)
    hover = plotting.create_hover_tool("MW", resolution)
    this_hour = time_utils.get_most_recent_hour().replace(year=2015)
    next4am = [dt for dt in [this_hour + timedelta(hours=i) for i in range(1, 25)] if dt.hour == 4][0]
    x_range = plotting.make_range(df_sum.index)
    fig_profile = plotting.create_graph(df_sum.y,
                                        title=plot_label,
                                        x_range=x_range,
                                        x_label="Time (sampled by %s)"
                                        % time_utils.freq_label_to_human_readable_label(resolution),
                                        y_label="Power (in MW)",
                                        legend=titleize(show_summed),
                                        hover_tool=hover)

    # TODO: show when user has (possible) actions in order book for a time slot
    if current_user.is_authenticated and (current_user.has_role("admin") or "wind" in current_user.email
                                          or "charging" in current_user.email):
        plotting.highlight(fig_profile, next4am, next4am + timedelta(hours=1), redirect_to="/control")

    fig_profile.plot_height = 450
    fig_profile.plot_width = 900
    fig_profile.sizing_mode = "stretch_both"

    df_stacked_data = pd.DataFrame(index=df_sum.index, columns=stack_types)
    for st in stack_types:
        df_stacked_data[st] = Resource(pluralize(st)).get_data(start=start, end=end, resolution=resolution)\
                                  .loc[:, ['y']]  # only get the y data
    stacked_value_mask(df_stacked_data)
    df_stacked_data = data_or_zeroes(df_stacked_data)
    df_stacked_areas = stacked(df_stacked_data)

    num_areas = df_stacked_areas.shape[1]
    if num_areas <= 2:
        colors = ['#99d594', '#dddd9d']
    else:
        colors = palettes.brewer['Spectral'][num_areas]
    x_points = np.hstack((df_stacked_data.index[::-1], df_stacked_data.index))

    fig_profile.grid.minor_grid_line_color = '#eeeeee'

    for a, area in enumerate(df_stacked_areas):
        fig_profile.patch(x_points, df_stacked_areas[area].values,
                          color=colors[a], alpha=0.8, line_color=None, legend=titleize(df_stacked_data.columns[a]))

    # actions
    df_actions = pd.DataFrame(index=df_sum.index, columns=["y"]).fillna(0)
    if next4am in df_actions.index:
        if current_user.is_authenticated:
            if current_user.has_role("admin"):
                df_actions.loc[next4am] = -2.4  # mock two actions
            elif "wind" in current_user.email:
                df_actions.loc[next4am] = -1.3  # mock one action
            elif "charging" in current_user.email:
                df_actions.loc[next4am] = -1.1  # mock one action
    next2am = [dt for dt in [this_hour + timedelta(hours=i) for i in range(1, 25)] if dt.hour == 2][0]
    if next2am in df_actions.index:
        if next2am < next4am and (current_user.is_authenticated and (current_user.has_role("admin")
                                                                     or "wind" in current_user.email
                                                                     or "charging" in current_user.email)):
            df_actions.loc[next2am] = 1.1  # mock the shift "payback" (actually occurs earlier in our mock example)
    next9am = [dt for dt in [this_hour + timedelta(hours=i) for i in range(1, 25)] if dt.hour == 9][0]
    if next9am in df_actions.index:
        df_actions.loc[next9am] = 3.5  # mock some other ordered actions that are not in an opportunity hour anymore

    fig_actions = plotting.create_graph(df_actions.y,
                                        title="Ordered balancing actions",
                                        x_range=x_range,
                                        y_label="Power (in MW)")
    if current_user.is_authenticated and (current_user.has_role("admin") or "wind" in current_user.email
                                          or "charging" in current_user.email):
        plotting.highlight(fig_actions, next4am, next4am + timedelta(hours=1), redirect_to="/control")

    fig_actions.plot_height = 150
    fig_actions.plot_width = fig_profile.plot_width
    fig_actions.sizing_mode = "fixed"
    fig_actions.xaxis.visible = False

    portfolio_plot_script, portfolio_plot_div = components(gridplot([fig_profile], [fig_actions],
                                                                    toolbar_options={'logo': None},
                                                                    sizing_mode='scale_width'))
    next24hours = [(time_utils.get_most_recent_hour() + timedelta(hours=i)).strftime("%I:00 %p") for i in range(1, 26)]

    return render_bvp_template("views/portfolio.html",
                               assets=assets,
                               asset_types=represented_asset_types,
                               production_per_asset=production_per_asset,
                               consumption_per_asset=consumption_per_asset,
                               profit_loss_energy_per_asset=profit_loss_energy_per_asset,
                               curtailment_per_asset=curtailment_per_asset,
                               shifting_per_asset=shifting_per_asset,
                               profit_loss_flexibility_per_asset=profit_loss_flexibility_per_asset,
                               production_per_asset_type=production_per_asset_type,
                               consumption_per_asset_type=consumption_per_asset_type,
                               profit_loss_energy_per_asset_type=profit_loss_energy_per_asset_type,
                               curtailment_per_asset_type=curtailment_per_asset_type,
                               shifting_per_asset_type=shifting_per_asset_type,
                               profit_loss_flexibility_per_asset_type=profit_loss_flexibility_per_asset_type,
                               sum_production=sum(production_per_asset_type.values()),
                               sum_consumption=sum(consumption_per_asset_type.values()),
                               sum_profit_loss_energy=sum(profit_loss_energy_per_asset_type.values()),
                               sum_curtailment=sum(curtailment_per_asset_type.values()),
                               sum_shifting=sum(shifting_per_asset_type.values()),
                               sum_profit_loss_flexibility=sum(profit_loss_flexibility_per_asset_type.values()),
                               portfolio_plots_script=portfolio_plot_script,
                               portfolio_plots_div=portfolio_plot_div,
                               next24hours=next24hours,
                               alt_stacking=show_summed)
