"""Tests for get_power_values sign-convention behavior.

These tests write beliefs into the database and mutate sensor attributes, so they require
the function-scoped ``fresh_db`` fixture to prevent state leaking between parametrized runs.
"""

import numpy as np
import pandas as pd
from datetime import timedelta

import pytest

import timely_beliefs as tb

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.planning.utils import get_power_values


@pytest.fixture()
def inflexible_power_sensor(fresh_db, app):
    """Create a fresh sensor with known power values for each test.

    The sensor stores a positive value (100 kW = 0.1 MW).  In FlexMeasures' default
    convention ``consumption_is_positive`` is *False*, so positive values represent
    production and must be negated when the scheduler needs consumption-positive MW values.
    """
    source = DataSource(name="inflexible-test-source", type="test")
    fresh_db.session.add(source)

    asset_type = GenericAssetType(name="inflexible-asset-type")
    fresh_db.session.add(asset_type)

    asset = GenericAsset(name="inflexible-asset", generic_asset_type=asset_type)
    fresh_db.session.add(asset)

    sensor = Sensor(
        name="inflexible-power",
        generic_asset=asset,
        event_resolution=timedelta(hours=1),
        unit="kW",
    )
    fresh_db.session.add(sensor)
    fresh_db.session.flush()  # ensure sensor.id is populated

    query_window = (
        pd.Timestamp("2025-06-01 00:00:00+00:00"),
        pd.Timestamp("2025-06-01 01:00:00+00:00"),
    )

    bdf = tb.BeliefsDataFrame(
        pd.DataFrame(
            {
                "event_start": pd.date_range(
                    start=query_window[0], freq="1h", periods=1
                ),
                "event_value": [100.0],  # 100 kW  →  0.1 MW after unit conversion
            }
        ),
        belief_horizon=pd.Timedelta(0),
        sensor=sensor,
        source=source,
        event_resolution=sensor.event_resolution,
    )
    TimedBelief.add(bdf)
    fresh_db.session.commit()

    return sensor, query_window


@pytest.mark.parametrize(
    "consumption_is_positive, expected_mw",
    [
        (True, 0.1),  # consumption-positive: return value unchanged
        (False, -0.1),  # production-positive: negate the stored value
    ],
)
def test_get_power_values_sign_convention(
    app, inflexible_power_sensor, consumption_is_positive, expected_mw
):
    """get_power_values respects an explicit ``consumption_is_positive`` override.

    The stored value is 100 kW (0.1 MW).

    * ``consumption_is_positive=True``  → return as-is  (+0.1 MW, consumption)
    * ``consumption_is_positive=False`` → negate        (-0.1 MW, production)
    """
    sensor, query_window = inflexible_power_sensor
    with app.app_context():
        result = get_power_values(
            query_window=query_window,
            resolution=timedelta(hours=1),
            beliefs_before=None,
            sensor=sensor,
            consumption_is_positive=consumption_is_positive,
        )
    assert isinstance(result, np.ndarray)
    assert len(result) == 1
    assert result[0] == pytest.approx(expected_mw)


def test_get_power_values_falls_back_to_sensor_attribute(app, inflexible_power_sensor):
    """get_power_values falls back to the sensor's ``consumption_is_positive`` attribute.

    When the parameter is ``None`` the sensor attribute is used:

    * Default (no attribute set)  → ``False`` → values are negated → -0.1 MW
    * After setting attribute to ``True`` → values returned unchanged → +0.1 MW
    """
    sensor, query_window = inflexible_power_sensor

    # No attribute set: default is False (production-positive), so value is negated.
    with app.app_context():
        result_default = get_power_values(
            query_window=query_window,
            resolution=timedelta(hours=1),
            beliefs_before=None,
            sensor=sensor,
            consumption_is_positive=None,
        )
    assert result_default[0] == pytest.approx(-0.1)

    # Explicitly set attribute to True (consumption-positive): value is returned as-is.
    sensor.attributes["consumption_is_positive"] = True
    with app.app_context():
        result_attr_true = get_power_values(
            query_window=query_window,
            resolution=timedelta(hours=1),
            beliefs_before=None,
            sensor=sensor,
            consumption_is_positive=None,
        )
    assert result_attr_true[0] == pytest.approx(0.1)
