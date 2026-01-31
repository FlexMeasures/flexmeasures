import pandas as pd
import numpy as np

from flexmeasures.data.models.planning import StockCommitment, FlowCommitment
from flexmeasures.data.models.planning.utils import (
    initialize_index,
    add_tiny_price_slope,
)
from flexmeasures.data.models.planning.linear_optimization import device_scheduler


def test_multi_feed_device_scheduler_shared_buffer():
    # ---- time setup
    start = pd.Timestamp("2026-01-01T00:00+01")
    end = pd.Timestamp("2026-01-02T00:00+01")
    resolution = pd.Timedelta("PT1H")
    index = initialize_index(start=start, end=end, resolution=resolution)

    # ---- three devices
    devices = ["gas boiler", "heat pump power", "battery power"]

    # ---- device grouping
    device_group = pd.Series(
        {
            0: "shared thermal buffer",  # gas boiler
            1: "shared thermal buffer",  # "heat pump power"
            2: "battery SoC",  # "battery power"
        }
    )
    device_commodity = pd.Series(
        {
            0: "gas",  # gas boiler
            1: "electricity",  # "heat pump power"
            2: "electricity",  # "battery power"
        }
    )
    equals = pd.Series(np.nan, index=index)
    equals[-1] = 100
    device_constraints = []
    for d, device_name in enumerate(devices):
        # 0 and 1 : derivative min 0
        # 2 : derivative min = - production capacity

        df = pd.DataFrame(
            {
                "min": 0,
                "max": 100,
                "equals": np.nan,
                "derivative min": 0 if d in (0, 1) else -20,
                "derivative max": 20,
                "derivative equals": np.nan,
                "derivative down efficiency": 0.9,
                "derivative up efficiency": 0.9,
            },
            index=index,
        )
        device_constraints.append(df)

    ems_constraints = pd.DataFrame(
        {
            "derivative min": -40,
            "derivative max": 40,
        },
        index=index,
    )

    # ---- shared buffer max = 100 (soft)
    max_soc = 100.0
    breach_price = 1_000.0
    min_soc = pd.Series(0, index=index)
    min_soc[-1] = 100

    # default commodity: electricity
    # choice: electricity or gas
    gas_price = pd.Series(300, index=index)
    electricity_price = pd.Series(600, index=index, name="event_value")
    electricity_price.iloc[12:14] = 200
    prices = {"gas": gas_price, "electricity": electricity_price}

    sloped_prices = (
        add_tiny_price_slope(electricity_price.to_frame())
        - electricity_price.to_frame()
    )

    commitments = []

    commitments.append(
        StockCommitment(
            name="buffer min",
            index=index,
            quantity=min_soc,
            upwards_deviation_price=0,
            downwards_deviation_price=-breach_price,
            # instead of device=None, I considered to create a series for the devices that we need for this
            # specific commitment.
            device=pd.Series([[0, 1]] * len(index), index=index),
            device_group=device_group,
        )
    )
    for d, dev in enumerate(devices):
        commitments.append(
            StockCommitment(
                name="buffer max",
                index=index,
                quantity=max_soc,
                upwards_deviation_price=breach_price,
                downwards_deviation_price=0,
                device=pd.Series(d, index=index),
                device_group=device_group,
            )
        )
        commitments.append(
            FlowCommitment(
                name=device_commodity[d],
                index=index,
                quantity=0,
                upwards_deviation_price=prices[device_commodity[d]],
                downwards_deviation_price=prices[device_commodity[d]],
                device=pd.Series(d, index=index),
                device_group=device_commodity,
            )
        )

        commitments.append(
            FlowCommitment(
                name="preferred_charge_sooner",
                index=index,
                quantity=0,
                upwards_deviation_price=sloped_prices,
                downwards_deviation_price=sloped_prices,
                device=pd.Series(d, index=index),
                device_group=device_commodity,
            )
        )

    # ---- run scheduler
    planned_power, planned_costs, results, model = device_scheduler(
        device_constraints=device_constraints,
        ems_constraints=ems_constraints,
        commitments=commitments,
        initial_stock=0,
    )

    # ---- sanity: model solved
    assert results.solver.termination_condition in ("optimal", "locallyOptimal")

    # ---- key assertion: exactly TWO commitment groups
    #   - one for "shared thermal buffer"
    #   - one for "battery SoC"
    #
    # i.e. NOT three (which would indicate per-device baselines)
    commitment_groups = set(commitments[0].device_group.values)

    commitment_costs = {
        "name": "commitment_costs",
        "data": {
            c.name: costs
            for c, costs in zip(commitments, model.commitment_costs.values())
        },
    }
    assert commitment_costs["data"]["electricity"] == -11440.0
    assert round(commitment_costs["data"]["gas"], 2) == 21333.33

    assert commitment_groups == {"shared thermal buffer"}

    # ---- key behavioural check:
    # total commitment cost should be <= 1 breach per group per timestep
    #
    # If baselines were duplicated, cost would be ~2x for the shared buffer.
    expected_max_cost = len(index) * breach_price * 2
    assert planned_costs <= expected_max_cost
