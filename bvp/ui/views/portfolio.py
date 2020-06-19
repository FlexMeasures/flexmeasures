from datetime import timedelta

from flask import request, session, current_app
from flask_security import roles_accepted
from flask_security.core import current_user
import pandas as pd
import numpy as np
from bokeh.embed import components
import bokeh.palettes as palettes

from bvp.utils import time_utils
from bvp.utils.bvp_inflection import capitalize, pluralize
from bvp.data.models.assets import Power
from bvp.data.models.markets import Price
from bvp.data.services.resources import Resource, get_assets, get_markets
import bvp.ui.utils.plotting_utils as plotting
from bvp.ui.views import bvp_ui
from bvp.ui.utils.view_utils import render_bvp_template


@bvp_ui.route("/portfolio", methods=["GET", "POST"])  # noqa: C901
@roles_accepted("admin", "Prosumer")
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

    assets = get_assets(order_by_asset_attribute="display_name", order_direction="asc")
    markets = get_markets()

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

    average_prices = {}
    for market in markets:
        average_prices[market.name] = Price.collect(
            [market.name], query_window=(start, end), resolution=resolution
        ).y.mean()
    prices_data = Price.collect(
        ["epex_da"], query_window=(start, end), resolution=resolution
    )

    load_hour_factor = time_utils.resolution_to_hour_factor(resolution)

    for asset in assets:
        power_data = Power.collect(
            [asset.name], query_window=(start, end), resolution=resolution
        )
        if prices_data.empty or power_data.empty:
            profit_loss_energy_per_asset[asset.name] = np.NaN
        else:
            profit_loss_energy_per_asset[asset.name] = pd.Series(
                power_data.y * load_hour_factor * prices_data.y, index=power_data.index
            ).sum()

        sum_production_or_consumption = pd.Series(power_data.y).sum() * load_hour_factor
        report_as = decide_direction_for_report(
            asset.asset_type.is_consumer,
            asset.asset_type.is_producer,
            sum_production_or_consumption,
        )

        if report_as == "consumer":
            production_per_asset[asset.name] = 0
            consumption_per_asset[asset.name] = -1 * sum_production_or_consumption
        elif report_as == "producer":
            production_per_asset[asset.name] = sum_production_or_consumption
            consumption_per_asset[asset.name] = 0

        neat_asset_type_name = pluralize(asset.asset_type.display_name)
        if neat_asset_type_name not in production_per_asset_type:
            represented_asset_types[neat_asset_type_name] = asset.asset_type
            production_per_asset_type[neat_asset_type_name] = 0.0
            consumption_per_asset_type[neat_asset_type_name] = 0.0
            profit_loss_energy_per_asset_type[neat_asset_type_name] = 0.0
            curtailment_per_asset_type[neat_asset_type_name] = 0.0
            shifting_per_asset_type[neat_asset_type_name] = 0.0
            profit_loss_flexibility_per_asset_type[neat_asset_type_name] = 0.0
        production_per_asset_type[neat_asset_type_name] += production_per_asset[
            asset.name
        ]
        consumption_per_asset_type[neat_asset_type_name] += consumption_per_asset[
            asset.name
        ]
        profit_loss_energy_per_asset_type[
            neat_asset_type_name
        ] += profit_loss_energy_per_asset[asset.name]

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
        curtailment_per_asset_type[neat_asset_type_name] += curtailment_per_asset[
            asset.name
        ]
        shifting_per_asset_type[neat_asset_type_name] += shifting_per_asset[asset.name]
        profit_loss_flexibility_per_asset_type[
            neat_asset_type_name
        ] += profit_loss_flexibility_per_asset[asset.name]

    # get data for stacked plot for the selected period

    def data_or_zeroes(df: pd.DataFrame) -> pd.DataFrame:
        """Making really sure we have the structure to let the plots not fail"""
        if df is None or df.empty:
            return pd.DataFrame(
                index=pd.date_range(
                    start=start,
                    end=end,
                    freq=resolution,
                    tz=time_utils.get_timezone(),
                    closed="left",
                ),
                columns=["y"],
            ).fillna(0)
        else:
            return df

    default_stack_side = "production"
    stack_types = {}
    if "building" in current_user.email or "charging" in current_user.email:
        default_stack_side = "consumption"
    show_stacked = request.values.get("show_stacked", default_stack_side)
    if show_stacked == "production":
        show_summed = "consumption"
        for t in represented_asset_types:
            if (
                decide_direction_for_report(
                    represented_asset_types[t].is_consumer,
                    represented_asset_types[t].is_producer,
                    production_per_asset_type[
                        pluralize(represented_asset_types[t].display_name)
                    ],
                )
                == "producer"
            ):
                stack_types[
                    pluralize(represented_asset_types[t].display_name)
                ] = represented_asset_types[t]
        sum_assets = [a.name for a in assets if a.asset_type.is_consumer is True]
        plot_label = "Stacked production vs aggregated consumption"
    else:
        show_summed = "production"
        for t in represented_asset_types:
            if (
                decide_direction_for_report(
                    represented_asset_types[t].is_consumer,
                    represented_asset_types[t].is_producer,
                    -1
                    * consumption_per_asset_type[
                        pluralize(represented_asset_types[t].display_name)
                    ],
                )
                == "consumer"
            ):
                stack_types[
                    pluralize(represented_asset_types[t].display_name)
                ] = represented_asset_types[t]
        sum_assets = [a.name for a in assets if a.asset_type.is_producer is True]
        plot_label = "Stacked consumption vs aggregated production"

    df_sum = Power.collect(
        sum_assets,
        query_window=(start, end),
        resolution=resolution,
        create_if_empty=True,
    )

    # Plot as positive values regardless of whether the summed data is production or consumption
    df_sum = data_or_zeroes(df_sum)
    if show_stacked == "production":
        df_sum.y *= -1

    this_hour = time_utils.get_most_recent_hour()
    if current_app.config.get("BVP_MODE", "") == "demo":
        this_hour = this_hour.replace(year=2015)
    next4am = [
        dt
        for dt in [this_hour + timedelta(hours=i) for i in range(1, 25)]
        if dt.hour == 4
    ][0]
    x_range = plotting.make_range(df_sum.index)
    fig_profile = plotting.create_graph(
        df_sum,
        unit="MW",
        title=plot_label,
        x_range=x_range,
        x_label="Time (resolution of %s)"
        % time_utils.freq_label_to_human_readable_label(resolution),
        y_label="Power (in MW)",
        legend_location="top_right",
        legend_labels=(capitalize(show_summed), None),
        show_y_floats=True,
        non_negative_only=True,
    )

    # TODO: show when user has (possible) actions in order book for a time slot
    if current_user.is_authenticated and (
        current_user.has_role("admin")
        or "wind" in current_user.email
        or "charging" in current_user.email
    ):
        plotting.highlight(
            fig_profile, next4am, next4am + timedelta(hours=1), redirect_to="/control"
        )

    fig_profile.plot_height = 450
    fig_profile.plot_width = 900

    df_stacked_data = pd.DataFrame(index=df_sum.index)
    for st in stack_types:
        data = Resource(st).get_data(
            start=start, end=end, resolution=resolution, create_if_empty=True
        )
        if not data.empty:
            df_stacked_data[capitalize(st)] = data.y.values

    # Plot as positive values regardless of whether the stacked data is production or consumption
    df_stacked_data = data_or_zeroes(df_stacked_data).fillna(0)
    if show_stacked == "consumption":
        df_stacked_data[:] *= -1
    df_stacked_areas = stack_df(df_stacked_data)

    num_areas = df_stacked_areas.shape[1]
    if num_areas <= 2:
        colors = ["#99d594", "#dddd9d"]
    else:
        colors = palettes.brewer["Spectral"][num_areas]

    df_stacked_data = time_utils.tz_index_naively(df_stacked_data)
    x_points = np.hstack((df_stacked_data.index[::-1], df_stacked_data.index))

    fig_profile.grid.minor_grid_line_color = "#eeeeee"

    for a, area in enumerate(df_stacked_areas):
        fig_profile.patch(
            x_points,
            df_stacked_areas[area].values,
            color=colors[a],
            alpha=0.8,
            line_color=None,
            legend=df_stacked_data.columns[a],
            level="underlay",
        )

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
    next2am = [
        dt
        for dt in [this_hour + timedelta(hours=i) for i in range(1, 25)]
        if dt.hour == 2
    ][0]
    if next2am in df_actions.index:
        if next2am < next4am and (
            current_user.is_authenticated
            and (
                current_user.has_role("admin")
                or "wind" in current_user.email
                or "charging" in current_user.email
            )
        ):
            # mock the shift "payback" (actually occurs earlier in our mock example)
            df_actions.loc[next2am] = 1.1
    next9am = [
        dt
        for dt in [this_hour + timedelta(hours=i) for i in range(1, 25)]
        if dt.hour == 9
    ][0]
    if next9am in df_actions.index:
        # mock some other ordered actions that are not in an opportunity hour anymore
        df_actions.loc[next9am] = 3.5

    fig_actions = plotting.create_graph(
        df_actions,
        unit="MW",
        title="Ordered balancing actions",
        x_range=x_range,
        y_label="Power (in MW)",
    )
    if current_user.is_authenticated and (
        current_user.has_role("admin")
        or "wind" in current_user.email
        or "charging" in current_user.email
    ):
        plotting.highlight(
            fig_actions, next4am, next4am + timedelta(hours=1), redirect_to="/control"
        )

    fig_actions.plot_height = 150
    fig_actions.plot_width = fig_profile.plot_width
    fig_actions.xaxis.visible = False

    portfolio_plots_script, portfolio_plots_divs = components(
        (fig_profile, fig_actions)
    )
    next24hours = [
        (time_utils.get_most_recent_hour() + timedelta(hours=i)).strftime("%I:00 %p")
        for i in range(1, 26)
    ]

    return render_bvp_template(
        "views/portfolio.html",
        assets=assets,
        average_prices=average_prices,
        asset_types=represented_asset_types,
        markets=markets,
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
        sum_profit_loss_flexibility=sum(
            profit_loss_flexibility_per_asset_type.values()
        ),
        portfolio_plots_script=portfolio_plots_script,
        portfolio_plots_divs=portfolio_plots_divs,
        next24hours=next24hours,
        alt_stacking=show_summed,
    )


def decide_direction_for_report(is_consumer, is_producer, sum_values) -> str:
    """returns "producer" or "consumer" """
    if is_consumer and not is_producer:
        return "consumer"
    elif is_producer and not is_consumer:
        return "producer"
    elif sum_values > 0:
        return "producer"
    else:
        return "consumer"


def stack_df(df: pd.DataFrame) -> pd.DataFrame:
    """Stack columns of df cumulatively, include bottom"""
    df_top = df.cumsum(axis=1)
    df_bottom = df_top.shift(axis=1).fillna(0)[::-1]
    df_stack = pd.concat([df_bottom, df_top], ignore_index=True)
    return df_stack
