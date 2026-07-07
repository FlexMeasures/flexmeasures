import pandas as pd
from datetime import timedelta

import pytest

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.schemas.sensors import SensorReference
from flexmeasures.data.models.planning.utils import get_series_from_quantity_or_sensor


def test_get_series_from_sensor_reference_source_filter_integration(fresh_db):
    """A :class:`SensorReference` with ``source_types`` returns only beliefs from matching sources.

    Two beliefs are stored for the same event: one from a "scheduler" source and one from a
    "forecaster" source. Querying via a :class:`SensorReference` with
    ``source_types=["scheduler"]`` returns only the scheduler value, while
    ``exclude_source_types=["scheduler"]`` returns only the forecaster value.
    """
    query_window = (
        pd.Timestamp("2025-06-01 08:00:00+02:00"),
        pd.Timestamp("2025-06-01 08:15:00+02:00"),
    )
    scheduler_source = DataSource(name="test-scheduler", type="scheduler")
    fresh_db.session.add(scheduler_source)
    forecaster_source = DataSource(name="test-forecaster", type="forecaster")
    fresh_db.session.add(forecaster_source)

    asset_type = GenericAssetType(name="test-asset-type-src-filter")
    fresh_db.session.add(asset_type)
    asset = GenericAsset(name="test-asset-src-filter", generic_asset_type=asset_type)
    fresh_db.session.add(asset)
    sensor = Sensor(
        name="test-sensor-src-filter",
        generic_asset=asset,
        event_resolution=timedelta(minutes=15),
        unit="kW",
    )
    fresh_db.session.add(sensor)
    fresh_db.session.flush()

    # Belief from scheduler source: value 100 kW
    scheduler_belief = TimedBelief(
        event_start=query_window[0],
        belief_horizon=timedelta(0),
        event_value=100.0,
        source=scheduler_source,
        sensor=sensor,
    )
    fresh_db.session.add(scheduler_belief)

    # Belief from forecaster source: value 200 kW
    forecaster_belief = TimedBelief(
        event_start=query_window[0],
        belief_horizon=timedelta(0),
        event_value=200.0,
        source=forecaster_source,
        sensor=sensor,
    )
    fresh_db.session.add(forecaster_belief)
    fresh_db.session.commit()

    # --- filter to scheduler only ---
    ref_scheduler = SensorReference(sensor=sensor, source_types=["scheduler"])
    result_scheduler = get_series_from_quantity_or_sensor(
        variable_quantity=ref_scheduler,
        query_window=query_window,
        resolution=sensor.event_resolution,
        unit="kW",
        as_instantaneous_events=False,
    )
    assert isinstance(result_scheduler, pd.Series)
    assert result_scheduler.iloc[0] == pytest.approx(100.0)

    # --- exclude scheduler (keep forecaster) ---
    ref_forecaster = SensorReference(sensor=sensor, exclude_source_types=["scheduler"])
    result_forecaster = get_series_from_quantity_or_sensor(
        variable_quantity=ref_forecaster,
        query_window=query_window,
        resolution=sensor.event_resolution,
        unit="kW",
        as_instantaneous_events=False,
    )
    assert isinstance(result_forecaster, pd.Series)
    assert result_forecaster.iloc[0] == pytest.approx(200.0)


def test_get_series_from_sensor_reference_sources_filter_integration(fresh_db):
    """A :class:`SensorReference` with ``sources`` returns only beliefs from the specified source.

    Two beliefs are stored for the same event from two different data sources. Querying via a
    :class:`SensorReference` with ``sources=[<one_source>]`` returns only the value associated
    with that source.
    """
    query_window = (
        pd.Timestamp("2025-06-01 10:00:00+02:00"),
        pd.Timestamp("2025-06-01 10:15:00+02:00"),
    )
    source_a = DataSource(name="test-source-a-ids", type="demo script")
    fresh_db.session.add(source_a)
    source_b = DataSource(name="test-source-b-ids", type="demo script")
    fresh_db.session.add(source_b)

    asset_type = GenericAssetType(name="test-asset-type-src-ids")
    fresh_db.session.add(asset_type)
    asset = GenericAsset(name="test-asset-src-ids", generic_asset_type=asset_type)
    fresh_db.session.add(asset)
    sensor = Sensor(
        name="test-sensor-src-ids",
        generic_asset=asset,
        event_resolution=timedelta(minutes=15),
        unit="kW",
    )
    fresh_db.session.add(sensor)
    fresh_db.session.flush()

    belief_a = TimedBelief(
        event_start=query_window[0],
        belief_horizon=timedelta(0),
        event_value=55.0,
        source=source_a,
        sensor=sensor,
    )
    fresh_db.session.add(belief_a)
    belief_b = TimedBelief(
        event_start=query_window[0],
        belief_horizon=timedelta(0),
        event_value=77.0,
        source=source_b,
        sensor=sensor,
    )
    fresh_db.session.add(belief_b)
    fresh_db.session.commit()

    ref = SensorReference(sensor=sensor, sources=[source_a])
    result = get_series_from_quantity_or_sensor(
        variable_quantity=ref,
        query_window=query_window,
        resolution=sensor.event_resolution,
        unit="kW",
        as_instantaneous_events=False,
    )
    assert isinstance(result, pd.Series)
    assert result.iloc[0] == pytest.approx(55.0)


def test_get_series_from_sensor_reference_source_account_filter_integration(fresh_db):
    """A :class:`SensorReference` with ``source_account`` returns only beliefs from the specified account's sources.

    Two beliefs are stored for the same event: one from a source linked to account A,
    and one from a source linked to account B. Querying with ``source_account=[account_a]``
    returns only the value associated with account A.
    """
    from flexmeasures.data.models.user import Account

    query_window = (
        pd.Timestamp("2025-06-01 14:00:00+02:00"),
        pd.Timestamp("2025-06-01 14:15:00+02:00"),
    )
    account_a = Account(name="test-account-a-src-acct")
    fresh_db.session.add(account_a)
    account_b = Account(name="test-account-b-src-acct")
    fresh_db.session.add(account_b)
    fresh_db.session.flush()

    source_a = DataSource(
        name="test-source-acct-a", type="demo script", account_id=account_a.id
    )
    fresh_db.session.add(source_a)
    source_b = DataSource(
        name="test-source-acct-b", type="demo script", account_id=account_b.id
    )
    fresh_db.session.add(source_b)

    asset_type = GenericAssetType(name="test-asset-type-src-acct")
    fresh_db.session.add(asset_type)
    asset = GenericAsset(name="test-asset-src-acct", generic_asset_type=asset_type)
    fresh_db.session.add(asset)
    sensor = Sensor(
        name="test-sensor-src-acct",
        generic_asset=asset,
        event_resolution=timedelta(minutes=15),
        unit="kW",
    )
    fresh_db.session.add(sensor)
    fresh_db.session.flush()

    belief_a = TimedBelief(
        event_start=query_window[0],
        belief_horizon=timedelta(0),
        event_value=33.0,
        source=source_a,
        sensor=sensor,
    )
    fresh_db.session.add(belief_a)
    belief_b = TimedBelief(
        event_start=query_window[0],
        belief_horizon=timedelta(0),
        event_value=66.0,
        source=source_b,
        sensor=sensor,
    )
    fresh_db.session.add(belief_b)
    fresh_db.session.commit()

    ref = SensorReference(sensor=sensor, source_account=[account_a])
    result = get_series_from_quantity_or_sensor(
        variable_quantity=ref,
        query_window=query_window,
        resolution=sensor.event_resolution,
        unit="kW",
        as_instantaneous_events=False,
    )
    assert isinstance(result, pd.Series)
    assert result.iloc[0] == pytest.approx(33.0)
