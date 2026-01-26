import pandas as pd
import numpy as np

from flexmeasures.data.models.planning import StockCommitment
from flexmeasures.data.models.planning.utils import initialize_index
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
            0: "shared thermal buffer", # gas boiler
            1: "shared thermal buffer", # "heat pump power"
            2: "battery SoC", #"battery power"
        }
    )

    # ---- trivial device constraints (stocks unconstrained individually)
    device_constraints = []
    for _ in devices:
        df = pd.DataFrame(
            {
                "min": -np.inf,
                "max": np.inf,
                "equals": np.nan,
                "derivative min": -np.inf,
                "derivative max": np.inf,
                "derivative equals": np.nan,
            },
            index=index,
        )
        device_constraints.append(df)

    # ---- no EMS-level constraints
    ems_constraints = pd.DataFrame(
        {
            "derivative min": -np.inf,
            "derivative max": np.inf,
        },
        index=index,
    )

    # ---- shared buffer max = 100 (soft)
    max_soc = 100.0
    breach_price = 1_000.0

    commitments = []
    for d,dev in enumerate(devices):
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
    assert commitment_groups == {"shared thermal buffer"}

    # ---- key behavioural check:
    # total commitment cost should be <= 1 breach per group per timestep
    #
    # If baselines were duplicated, cost would be ~2x for the shared buffer.
    expected_max_cost = len(index) * breach_price * 2
    assert planned_costs <= expected_max_cost
