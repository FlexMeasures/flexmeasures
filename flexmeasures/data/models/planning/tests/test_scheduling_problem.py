"""Tests for the solver-agnostic input preparation in the scheduling_problem module."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from flexmeasures.data.models.planning import FlowCommitment, StockCommitment
from flexmeasures.data.models.planning.scheduling_problem import (
    prepare_scheduling_problem,
)
from flexmeasures.data.models.planning.utils import initialize_df

COLUMNS = [
    "equals",
    "max",
    "min",
    "efficiency",
    "derivative equals",
    "derivative max",
    "derivative min",
    "derivative down efficiency",
    "derivative up efficiency",
    "stock delta",
]

START = pd.Timestamp("2020-01-01T00:00:00")
END = pd.Timestamp("2020-01-01T04:00:00")
RESOLUTION = timedelta(hours=1)


def make_device_constraints() -> pd.DataFrame:
    device_constraints = initialize_df(COLUMNS, START, END, RESOLUTION)
    device_constraints["max"] = 1
    device_constraints["min"] = -1
    device_constraints["derivative max"] = 0.5
    device_constraints["derivative min"] = -0.5
    return device_constraints


def make_problem_kwargs(commitments) -> dict:
    return dict(
        device_constraints=[make_device_constraints()],
        ems_constraints=initialize_df(COLUMNS, START, END, RESOLUTION),
        commitments=commitments,
    )


def make_index() -> pd.DatetimeIndex:
    return initialize_df(COLUMNS, START, END, RESOLUTION).index


def test_ems_level_flow_commitment_is_accepted():
    """A flow commitment naming no device binds at the EMS level, over all devices."""
    commitment = FlowCommitment(
        name="energy",
        quantity=0,
        upwards_deviation_price=1,
        downwards_deviation_price=-1,
        index=make_index(),
    )
    prepare_scheduling_problem(**make_problem_kwargs([commitment]))


def test_device_scoped_stock_commitment_is_accepted():
    """A stock commitment naming a device binds through its device group."""
    index = make_index()
    commitment = StockCommitment(
        name="soc",
        quantity=0.5,
        upwards_deviation_price=1,
        downwards_deviation_price=-1,
        device=pd.Series(0, index=index),
        index=index,
    )
    prepare_scheduling_problem(**make_problem_kwargs([commitment]))


def test_ems_level_stock_commitment_is_rejected():
    """A stock commitment naming no device or stock group reaches no constraint family."""
    commitment = StockCommitment(
        name="soc",
        quantity=0.5,
        upwards_deviation_price=1,
        downwards_deviation_price=-1,
        index=make_index(),
    )
    with pytest.raises(
        ValueError, match="Commitment 'soc' .* no constraint would bind it"
    ):
        prepare_scheduling_problem(**make_problem_kwargs([commitment]))


def test_commodity_commitment_without_devices_is_rejected():
    """An EMS-level flow commitment for a commodity that no commitment maps devices to is unenforceable."""
    commitment = FlowCommitment(
        name="gas price",
        quantity=0,
        upwards_deviation_price=1,
        downwards_deviation_price=-1,
        commodity="gas",
        index=make_index(),
    )
    with pytest.raises(ValueError, match="Commitment 'gas price' .* commodity 'gas'"):
        prepare_scheduling_problem(**make_problem_kwargs([commitment]))


def test_commodity_commitment_with_devices_is_accepted():
    """The same commodity commitment passes once another commitment maps devices to the commodity."""
    index = make_index()
    ems_level_commitment = FlowCommitment(
        name="gas price",
        quantity=0,
        upwards_deviation_price=1,
        downwards_deviation_price=-1,
        commodity="gas",
        index=index,
    )
    device_commitment = FlowCommitment(
        name="gas capacity",
        quantity=0,
        upwards_deviation_price=1,
        downwards_deviation_price=-1,
        device=pd.Series(0, index=index),
        commodity=pd.Series({0: "gas"}),
        index=index,
    )
    prepare_scheduling_problem(
        **make_problem_kwargs([ems_level_commitment, device_commitment])
    )
