from datetime import datetime, timedelta
from typing import Dict, List

from flask import request, session, current_app
from flask_security import roles_accepted
from flask_security.core import current_user
import pandas as pd
import numpy as np
from bokeh.embed import components
import bokeh.palettes as palettes
from bokeh.plotting import Figure

from flexmeasures.data.models.assets import Asset, Power
from flexmeasures.data.models.markets import Price
from flexmeasures.data.queries.portfolio import (
    get_structure,
    get_power_data,
    get_price_data,
)
from flexmeasures.data.services.resources import get_assets
from flexmeasures.utils import time_utils
from flexmeasures.utils.flexmeasures_inflection import capitalize
import flexmeasures.ui.utils.plotting_utils as plotting
from flexmeasures.ui.views import flexmeasures_ui
from flexmeasures.ui.utils.view_utils import (
    render_flexmeasures_template,
    set_time_range_for_session,
)


@flexmeasures_ui.route("/portfolio", methods=["GET", "POST"])
@roles_accepted("admin", "Prosumer")
def portfolio_view():  # noqa: C901
    """Portfolio view.
    By default, this page shows live results (production, consumption and market data) from the user's portfolio.
    Time windows for which the platform has identified upcoming balancing opportunities are highlighted.
    The page can also be used to navigate historical results.
    """

    set_time_range_for_session()
    start = session.get("start_time")
    end = session.get("end_time")
    resolution = session.get("resolution")

    # Get plot perspective
    perspectives = ["production", "consumption"]
    default_stack_side = "production"  # todo: move to user config setting
    show_stacked = request.values.get("show_stacked", default_stack_side)
    perspectives.remove(show_stacked)
    show_summed: str = perspectives[0]
    plot_label = f"Stacked {show_stacked} vs aggregated {show_summed}"

    # Get structure and data
    assets: List[Asset] = get_assets(
        order_by_asset_attribute="display_name", order_direction="asc"
    )
    represented_asset_types, markets, resource_dict = get_structure(assets)
    for resource_name, resource in resource_dict.items():
        resource.load_sensor_data(
            [Power, Price],
            start=start,
            end=end,
            resolution=resolution,
            exclude_source_types=["scheduling script"],
        )  # The resource caches the results
    (
        supply_resources_df_dict,
        demand_resources_df_dict,
        production_per_asset_type,
        consumption_per_asset_type,
        production_per_asset,
        consumption_per_asset,
    ) = get_power_data(resource_dict)
    price_bdf_dict, average_price_dict = get_price_data(resource_dict)

    # Pick a perspective for summing and for stacking
    sum_dict = (
        demand_resources_df_dict.values()
        if show_summed == "consumption"
        else supply_resources_df_dict.values()
    )
    power_sum_df = (
        pd.concat(sum_dict, axis=1).sum(axis=1).to_frame(name="event_value")
        if sum_dict
        else pd.DataFrame()
    )

    # Create summed plot
    power_sum_df = data_or_zeroes(power_sum_df, start, end, resolution)
    x_range = plotting.make_range(
        pd.date_range(start, end, freq=resolution, closed="left")
    )
    fig_profile = plotting.create_graph(
        power_sum_df,
        unit="MW",
        title=plot_label,
        x_range=x_range,
        x_label="Time (resolution of %s)"
        % time_utils.freq_label_to_human_readable_label(resolution),
        y_label="Power (in MW)",
        legend_location="top_right",
        legend_labels=(capitalize(show_summed), None, None),
        show_y_floats=True,
        non_negative_only=True,
    )
    fig_profile.plot_height = 450
    fig_profile.plot_width = 900

    # Create stacked plot
    stack_dict = (
        rename_event_value_column_to_resource_name(supply_resources_df_dict).values()
        if show_summed == "consumption"
        else rename_event_value_column_to_resource_name(
            demand_resources_df_dict
        ).values()
    )
    df_stacked_data = pd.concat(stack_dict, axis=1) if stack_dict else pd.DataFrame()
    df_stacked_data = data_or_zeroes(df_stacked_data, start, end, resolution)
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

    portfolio_plots_script, portfolio_plots_divs = components(fig_profile)

    # Flexibility numbers and a mocked control action are mocked for demo mode at the moment
    flex_info = {}
    if current_app.config.get("FLEXMEASURES_MODE") == "demo":
        flex_info = mock_flex_info(assets, represented_asset_types)
        fig_actions = mock_flex_figure(
            x_range, power_sum_df.index, fig_profile.plot_width
        )
        mock_flex_action_in_main_figure(fig_profile)
        portfolio_plots_script, portfolio_plots_divs = components(
            (fig_profile, fig_actions)
        )

    return render_flexmeasures_template(
        "views/portfolio.html",
        assets=assets,
        average_prices=average_price_dict,
        asset_types=represented_asset_types,
        markets=markets,
        production_per_asset=production_per_asset,
        consumption_per_asset=consumption_per_asset,
        production_per_asset_type=production_per_asset_type,
        consumption_per_asset_type=consumption_per_asset_type,
        sum_production=sum(production_per_asset_type.values()),
        sum_consumption=sum(consumption_per_asset_type.values()),
        flex_info=flex_info,
        portfolio_plots_script=portfolio_plots_script,
        portfolio_plots_divs=portfolio_plots_divs,
        alt_stacking=show_summed,
        fm_mode=current_app.config.get("FLEXMEASURES_MODE"),
    )


def data_or_zeroes(df: pd.DataFrame, start, end, resolution) -> pd.DataFrame:
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
            columns=["event_value"],
        ).fillna(0)
    else:
        return df.fillna(0)


def stack_df(df: pd.DataFrame) -> pd.DataFrame:
    """Stack columns of df cumulatively, include bottom"""
    df_top = df.cumsum(axis=1)
    df_bottom = df_top.shift(axis=1).fillna(0)[::-1]
    df_stack = pd.concat([df_bottom, df_top], ignore_index=True)
    return df_stack


def rename_event_value_column_to_resource_name(
    df_dict: Dict[str, pd.DataFrame]
) -> Dict[str, pd.DataFrame]:
    """Replace the column name "event_source" with the resource name, for each resource in the dictionary."""
    return {
        df_name: df.rename(columns={"event_value": capitalize(df_name)})
        for df_name, df in df_dict.items()
    }


def mock_flex_info(assets, represented_asset_types) -> dict:
    flex_info = dict(
        curtailment_per_asset={a.name: 0.0 for a in assets},
        shifting_per_asset={a.name: 0.0 for a in assets},
        profit_loss_flexibility_per_asset={a.name: 0.0 for a in assets},
        curtailment_per_asset_type={k: 0.0 for k in represented_asset_types.keys()},
        shifting_per_asset_type={k: 0.0 for k in represented_asset_types.keys()},
        profit_loss_flexibility_per_asset_type={
            k: 0.0 for k in represented_asset_types.keys()
        },
    )

    flex_info["shifting_per_asset"]["48_r"] = 1.1
    flex_info["profit_loss_flexibility_per_asset"]["48_r"] = 76000.0
    flex_info["shifting_per_asset_type"]["one-way EVSE"] = flex_info[
        "shifting_per_asset"
    ]["48_r"]
    flex_info["profit_loss_flexibility_per_asset_type"]["one-way EVSE"] = flex_info[
        "profit_loss_flexibility_per_asset"
    ]["48_r"]
    flex_info["curtailment_per_asset"]["hw-onshore"] = 1.3
    flex_info["profit_loss_flexibility_per_asset"]["hw-onshore"] = 84000.0
    flex_info["curtailment_per_asset_type"]["wind turbines"] = flex_info[
        "curtailment_per_asset"
    ]["hw-onshore"]
    flex_info["profit_loss_flexibility_per_asset_type"]["wind turbines"] = flex_info[
        "profit_loss_flexibility_per_asset"
    ]["hw-onshore"]

    flex_info["sum_curtailment"] = sum(flex_info["curtailment_per_asset_type"].values())  # type: ignore
    flex_info["sum_shifting"] = sum(flex_info["shifting_per_asset_type"].values())  # type: ignore
    flex_info["sum_profit_loss_flexibility"] = sum(  # type: ignore
        flex_info["profit_loss_flexibility_per_asset_type"].values()  # type: ignore
    )
    return flex_info


def mock_flex_figure(x_range, x_index, fig_width) -> Figure:
    df_actions = pd.DataFrame(index=x_index, columns=["event_value"]).fillna(0)
    next_action_hour4 = get_flex_action_hour(4)
    if next_action_hour4 in df_actions.index:
        if current_user.is_authenticated:
            if current_user.has_role("admin"):
                df_actions.loc[next_action_hour4] = -2.4  # mock two actions
            elif "wind" in current_user.email:
                df_actions.loc[next_action_hour4] = -1.3  # mock one action
            elif "charging" in current_user.email:
                df_actions.loc[next_action_hour4] = -1.1  # mock one action

    next_action_hour2 = get_flex_action_hour(2)
    if next_action_hour2 in df_actions.index:
        if next_action_hour2 < next_action_hour4 and (
            current_user.is_authenticated
            and (
                current_user.has_role("admin")
                or "wind" in current_user.email
                or "charging" in current_user.email
            )
        ):
            # mock the shift "payback" (actually occurs earlier in our mock example)
            df_actions.loc[next_action_hour2] = 1.1

    next_action_hour9 = get_flex_action_hour(9)
    if next_action_hour9 in df_actions.index:
        # mock some other ordered actions that are not in an opportunity hour anymore
        df_actions.loc[next_action_hour9] = 3.5

    fig_actions = plotting.create_graph(
        df_actions,
        unit="MW",
        title="Ordered balancing actions",
        x_range=x_range,
        y_label="Power (in MW)",
    )
    fig_actions.plot_height = 150
    fig_actions.plot_width = fig_width
    fig_actions.xaxis.visible = False

    if current_user.is_authenticated and (
        current_user.has_role("admin")
        or "wind" in current_user.email
        or "charging" in current_user.email
    ):
        plotting.highlight(
            fig_actions,
            next_action_hour4,
            next_action_hour4 + timedelta(hours=1),
            redirect_to="/control",
        )
    return fig_actions


def mock_flex_action_in_main_figure(fig_profile: Figure):
    # show when user has (possible) actions in order book for a time slot
    if current_user.is_authenticated and (
        current_user.has_role("admin")
        or "wind" in current_user.email
        or "charging" in current_user.email
    ):
        next_action_hour = get_flex_action_hour(4)
        plotting.highlight(
            fig_profile,
            next_action_hour,
            next_action_hour + timedelta(hours=1),
            redirect_to="/control",
        )


def get_flex_action_hour(h: int) -> datetime:
    """ get the next hour from now on """
    this_hour = time_utils.get_most_recent_hour()
    return [
        dt
        for dt in [this_hour + timedelta(hours=i) for i in range(1, 25)]
        if dt.hour == h
    ][0]
