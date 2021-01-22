from typing import List, Tuple, Union

from flask import current_app
import pandas as pd
import numpy as np
from pandas.tseries.frequencies import to_offset
from pyomo.core import (
    ConcreteModel,
    Var,
    RangeSet,
    Param,
    Reals,
    Constraint,
    Objective,
    minimize,
)
from pyomo.environ import UnknownSolver  # noqa F401
from pyomo.environ import value
from pyomo.opt import SolverFactory

from flexmeasures.data.models.planning.utils import initialize_series

infinity = float("inf")


def device_scheduler(  # noqa C901
    device_constraints: List[pd.DataFrame],
    ems_constraints: pd.DataFrame,
    commitment_quantities: List[pd.Series],
    commitment_downwards_deviation_price: Union[List[pd.Series], List[float]],
    commitment_upwards_deviation_price: Union[List[pd.Series], List[float]],
) -> Tuple[List[pd.Series], float]:
    """Schedule devices given constraints on a device and EMS level, and given a list of commitments by the EMS.
    The commitments are assumed to be with regards to the flow of energy to the device (positive for consumption,
    negative for production). The solver minimises the costs of deviating from the commitments.

    Device constraints are on a device level. Handled constraints (listed by column name):
        max: maximum stock assuming an initial stock of zero (e.g. in MWh or boxes)
        min: minimum stock assuming an initial stock of zero
        equal: exact amount of stock (we do this by clamping min and max)
        derivative max: maximum flow (e.g. in MW or boxes/h)
        derivative min: minimum flow
        derivative equals: exact amount of flow (we do this by clamping derivative min and derivative max)
    EMS constraints are on an EMS level. Handled constraints (listed by column name):
        derivative max: maximum flow
        derivative min: minimum flow
    Commitments are on an EMS level. Parameter explanations:
        commitment_quantities: amounts of flow specified in commitments (both previously ordered and newly requested)
            - e.g. in MW or boxes/h
        commitment_downwards_deviation_price: penalty for downwards deviations of the flow
            - e.g. in EUR/MW or EUR/(boxes/h)
            - either a single value (same value for each flow value) or a Series (different value for each flow value)
        commitment_upwards_deviation_price: penalty for upwards deviations of the flow

    All Series and DataFrames should have the same resolution.

    For now we pass in the various constraints and prices as separate variables, from which we make a MultiIndex
    DataFrame. Later we could pass in a MultiIndex DataFrame directly.
    """

    # If the EMS has no devices, don't bother
    if len(device_constraints) == 0:
        return [], 0

    # Check if commitments have the same time window and resolution as the constraints
    start = device_constraints[0].index.to_pydatetime()[0]
    resolution = pd.to_timedelta(device_constraints[0].index.freq)
    end = device_constraints[0].index.to_pydatetime()[-1] + resolution
    if len(commitment_quantities) != 0:
        start_c = commitment_quantities[0].index.to_pydatetime()[0]
        resolution_c = pd.to_timedelta(commitment_quantities[0].index.freq)
        end_c = commitment_quantities[0].index.to_pydatetime()[-1] + resolution
        if not (start_c == start and end_c == end):
            raise Exception(
                "Not implemented for different time windows.\n(%s,%s)\n(%s,%s)"
                % (start, end, start_c, end_c)
            )
        if resolution_c != resolution:
            raise Exception(
                "Not implemented for different resolutions.\n%s\n%s"
                % (resolution, resolution_c)
            )

    # Turn prices per commitment into prices per commitment flow
    if len(commitment_downwards_deviation_price) != 0:
        if all(
            isinstance(price, float) for price in commitment_downwards_deviation_price
        ):
            commitment_downwards_deviation_price = [
                initialize_series(price, start, end, resolution)
                for price in commitment_downwards_deviation_price
            ]
    if len(commitment_upwards_deviation_price) != 0:
        if all(
            isinstance(price, float) for price in commitment_upwards_deviation_price
        ):
            commitment_upwards_deviation_price = [
                initialize_series(price, start, end, resolution)
                for price in commitment_upwards_deviation_price
            ]

    model = ConcreteModel()

    # Add indices for devices (d), datetimes (j) and commitments (c)
    model.d = RangeSet(0, len(device_constraints) - 1, doc="Set of devices")
    model.j = RangeSet(
        0, len(device_constraints[0].index.to_pydatetime()) - 1, doc="Set of datetimes"
    )
    model.c = RangeSet(0, len(commitment_quantities) - 1, doc="Set of commitments")

    # Add parameters
    def price_down_select(m, c, j):
        return commitment_downwards_deviation_price[c].iloc[j]

    def price_up_select(m, c, j):
        return commitment_upwards_deviation_price[c].iloc[j]

    def commitment_quantity_select(m, c, j):
        return commitment_quantities[c].iloc[j]

    def device_max_select(m, d, j):
        max_v = device_constraints[d]["max"].iloc[j]
        equal_v = device_constraints[d]["equals"].iloc[j]
        if np.isnan(max_v) and np.isnan(equal_v):
            return infinity
        else:
            return np.nanmin([max_v, equal_v])

    def device_min_select(m, d, j):
        min_v = device_constraints[d]["min"].iloc[j]
        equal_v = device_constraints[d]["equals"].iloc[j]
        if np.isnan(min_v) and np.isnan(equal_v):
            return -infinity
        else:
            return np.nanmax([min_v, equal_v])

    def device_derivative_max_select(m, d, j):
        max_v = device_constraints[d]["derivative max"].iloc[j]
        equal_v = device_constraints[d]["derivative equals"].iloc[j]
        if np.isnan(max_v) and np.isnan(equal_v):
            return infinity
        else:
            return np.nanmin([max_v, equal_v])

    def device_derivative_min_select(m, d, j):
        min_v = device_constraints[d]["derivative min"].iloc[j]
        equal_v = device_constraints[d]["derivative equals"].iloc[j]
        if np.isnan(min_v) and np.isnan(equal_v):
            return -infinity
        else:
            return np.nanmax([min_v, equal_v])

    def ems_derivative_max_select(m, j):
        v = ems_constraints["derivative max"].iloc[j]
        if np.isnan(v):
            return infinity
        else:
            return v

    def ems_derivative_min_select(m, j):
        v = ems_constraints["derivative min"].iloc[j]
        if np.isnan(v):
            return -infinity
        else:
            return v

    model.up_price = Param(model.c, model.j, initialize=price_up_select)
    model.down_price = Param(model.c, model.j, initialize=price_down_select)
    model.commitment_quantity = Param(
        model.c, model.j, initialize=commitment_quantity_select
    )
    model.device_max = Param(model.d, model.j, initialize=device_max_select)
    model.device_min = Param(model.d, model.j, initialize=device_min_select)
    model.device_derivative_max = Param(
        model.d, model.j, initialize=device_derivative_max_select
    )
    model.device_derivative_min = Param(
        model.d, model.j, initialize=device_derivative_min_select
    )
    model.ems_derivative_max = Param(model.j, initialize=ems_derivative_max_select)
    model.ems_derivative_min = Param(model.j, initialize=ems_derivative_min_select)

    # Add variables
    model.power = Var(model.d, model.j, domain=Reals, initialize=0)

    # Add constraints as a tuple of (lower bound, value, upper bound)
    def device_bounds(m, d, j):
        return (
            m.device_min[d, j],
            sum(m.power[d, k] for k in range(0, j + 1)),
            m.device_max[d, j],
        )

    def device_derivative_bounds(m, d, j):
        return (
            m.device_derivative_min[d, j],
            m.power[d, j],
            m.device_derivative_max[d, j],
        )

    def ems_derivative_bounds(m, j):
        return m.ems_derivative_min[j], sum(m.power[:, j]), m.ems_derivative_max[j]

    model.device_energy_bounds = Constraint(model.d, model.j, rule=device_bounds)
    model.device_power_bounds = Constraint(
        model.d, model.j, rule=device_derivative_bounds
    )
    model.ems_power_bounds = Constraint(model.j, rule=ems_derivative_bounds)

    # Add objective
    def cost_function(m):
        costs = 0
        for c in m.c:
            for j in m.j:
                ems_power_in_j = sum(m.power[d, j] for d in m.d)
                ems_power_deviation = ems_power_in_j - m.commitment_quantity[c, j]
                if value(ems_power_deviation) >= 0:
                    costs += ems_power_deviation * m.up_price[c, j]
                else:
                    costs += ems_power_deviation * m.down_price[c, j]
        return costs

    model.costs = Objective(rule=cost_function, sense=minimize)

    # Solve
    SolverFactory(current_app.config.get("FLEXMEASURES_LP_SOLVER")).solve(model)

    planned_costs = value(model.costs)
    planned_power_per_device = []
    for d in model.d:
        planned_device_power = [model.power[d, j].value for j in model.j]
        planned_power_per_device.append(
            pd.Series(
                index=pd.date_range(
                    start=start, end=end, freq=to_offset(resolution), closed="left"
                ),
                data=planned_device_power,
            )
        )

    # model.pprint()
    # print(planned_costs)
    # input()
    return planned_power_per_device, planned_costs
