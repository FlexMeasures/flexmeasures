import altair as alt

from .defaults import (
    determine_k_unit_str,
    HEIGHT,
    K_TITLE,
    REDUCED_HEIGHT,
    SELECTOR_COLOR,
    TIME_FORMAT,
    TIME_SELECTION_TOOLTIP,
    TIME_TITLE,
    TIME_TOOLTIP_TITLE,
    WIDTH,
)


def bar_chart(dataset_name: str, agg_demand_unit: str):
    """ Bar chart for process data, showing only their total demand. """
    k_unit_str = determine_k_unit_str(agg_demand_unit)
    return (
        alt.Chart(data={"name": dataset_name})
        .mark_bar()
        .encode(
            x=alt.X("dt:T", title=TIME_TITLE),
            y=alt.Y("sum(k):Q", title=f"{K_TITLE} ({k_unit_str})"),
            tooltip=[
                alt.Tooltip(
                    "full_date:N",
                    title=TIME_TOOLTIP_TITLE,
                ),
                alt.Tooltip(
                    "sum(k):Q",
                    title=f"{K_TITLE} ({k_unit_str})",
                ),
            ],
        )
    )


def bar_chart_with_time_selection(dataset_name: str, agg_demand_unit: str):
    """Time selector above a bar chart for process data, showing only their total demand.

    Both charts plot consumption rate k against datetime dt.
    The time selector has an interval selection on dt.
    """
    k_unit_str = determine_k_unit_str(agg_demand_unit)
    dt_selection_brush = alt.selection_interval(encodings=["x"], name="dt_select")
    base = (
        alt.Chart(data={"name": dataset_name})
        .encode(
            x=alt.X("dt:T", title=TIME_TITLE),
            y=alt.Y("sum(k):Q", title=None, axis=None),
        )
        .transform_calculate(
            full_date=alt.expr.funcs.timeFormat(alt.datum.dt, TIME_FORMAT),
        )
    )
    dt_k_selection_plot = (
        base.mark_area(
            interpolate="step",
            color=SELECTOR_COLOR,
            tooltip=TIME_SELECTION_TOOLTIP,
        )
        .properties(height=REDUCED_HEIGHT, width=WIDTH)
        .add_selection(dt_selection_brush)
    )
    dt_k_plot = (
        base.mark_bar()
        .encode(
            x2="dt_e:T",
            y=alt.Y("sum(k):Q", stack="zero", title=f"{K_TITLE} ({k_unit_str})"),
            tooltip=[
                alt.Tooltip(
                    "full_date:N",
                    title=TIME_TOOLTIP_TITLE,
                ),
                alt.Tooltip(
                    "sum(k):Q",
                    title=f"{K_TITLE} ({k_unit_str})",
                ),
            ],
        )
        .properties(height=HEIGHT, width=WIDTH)
        .transform_filter(dt_selection_brush)
    )
    return alt.vconcat(dt_k_selection_plot, dt_k_plot)
