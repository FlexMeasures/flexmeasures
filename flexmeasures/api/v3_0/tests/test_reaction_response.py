"""The serialization of reaction rules onto served schedule values, slot by slot."""

from datetime import timedelta

import pandas as pd
import pytest

from flexmeasures.api.v3_0.sensors import _build_reaction_response

START = pd.Timestamp("2026-01-01T00:00:00+01:00")


def _meta(react, reference, band):
    """Rules at a 5-minute resolution, from per-slot lists."""
    return {
        "start": START.isoformat(),
        "resolution": "PT5M",
        "unit": "MW",
        "react": react,
        "reference": reference,
        "band": band,
    }


def test_coarser_sensor_gets_the_rule_only_where_the_sub_slots_agree():
    """Rules at 5 minutes served on 15-minute values keep a rule only where the sub-slots agree.

    An agreeing slot keeps its rule;
    a slot whose sub-slots disagree, or whose value lies outside the band, gets react 0, the mean reference and the value as band.
    """
    wide = [[0.0, 0.0], [0.0014, 0.0074]]
    narrow = [[0.002, 0.0074]]
    meta = _meta(
        react=[1, 1, 1, 1, 1, 1, 1, 1, 1],
        reference=[-0.0044] * 3 + [-0.0044, -0.0044, -0.0038] + [-0.0044] * 3,
        band=[wide] * 3 + [wide, wide, narrow] + [wide] * 3,
    )
    values = pd.Series(
        [0.0044, 0.0044, 0.001],  # the last value falls in the hole of an agreeing band
        index=pd.date_range(START, periods=3, freq="15min"),
    )
    reaction = _build_reaction_response(
        meta,
        values=values,
        resolution=timedelta(minutes=15),
        to_unit="MW",
        sign=1,
        device="charger",
    )
    assert reaction[0] == {
        "reference": -0.0044,
        "react": 1.0,
        "band": [[0.0, 0.0], [0.0014, 0.0074]],
    }
    assert reaction[1]["react"] == 0 and reaction[1]["band"] == [[0.0044, 0.0044]]
    assert reaction[1]["reference"] == pytest.approx((-0.0044 * 2 - 0.0038) / 3)
    assert reaction[2] == {"reference": -0.0044, "react": 0.0, "band": [[0.001, 0.001]]}


def test_finer_sensor_gets_each_rule_as_is():
    """Rules at 5 minutes served on 1-minute values: each value gets the one rule of its slot."""
    meta = _meta(
        react=[1, 0],
        reference=[-0.001, -0.002],
        band=[[[0.0, 0.002]], [[0.001, 0.001]]],
    )
    values = pd.Series(  # in kW, the served unit
        [1.0] * 10,
        index=pd.date_range(START, periods=10, freq="1min"),
    )
    reaction = _build_reaction_response(
        meta,
        values=values,
        resolution=timedelta(minutes=1),
        to_unit="kW",
        sign=1,
        device="charger",
    )
    assert [r["react"] for r in reaction] == [1.0] * 5 + [0.0] * 5
    assert reaction[0] == {"reference": -1.0, "react": 1.0, "band": [[0.0, 2.0]]}
    assert reaction[-1] == {"reference": -2.0, "react": 0.0, "band": [[1.0, 1.0]]}
