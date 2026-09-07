import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.schemas.sensors import SensorReference
from flexmeasures.data.models.planning.storage import StorageScheduler
from flexmeasures.data.models.planning.utils import get_series_from_quantity_or_sensor
from flexmeasures.utils.unit_utils import ur


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


def test_get_series_from_sensor_reference_default_fills_missing_values(fresh_db):
    """A SensorReference default fills query slots with no matching sensor belief."""
    query_window = (
        pd.Timestamp("2025-06-01 08:00:00+02:00"),
        pd.Timestamp("2025-06-01 08:30:00+02:00"),
    )
    source = DataSource(name="test-default-source", type="scheduler")
    fresh_db.session.add(source)
    asset_type = GenericAssetType(name="test-asset-type-default")
    fresh_db.session.add(asset_type)
    asset = GenericAsset(name="test-asset-default", generic_asset_type=asset_type)
    fresh_db.session.add(asset)
    sensor = Sensor(
        name="test-sensor-default",
        generic_asset=asset,
        event_resolution=timedelta(minutes=15),
        unit="MW",
    )
    fresh_db.session.add(sensor)
    fresh_db.session.flush()
    fresh_db.session.add(
        TimedBelief(
            event_start=query_window[0],
            belief_horizon=timedelta(0),
            event_value=0.1,
            source=source,
            sensor=sensor,
        )
    )
    fresh_db.session.commit()

    result = get_series_from_quantity_or_sensor(
        variable_quantity=SensorReference(sensor=sensor, default=ur.Quantity("1 MW")),
        query_window=query_window,
        resolution=sensor.event_resolution,
        unit="kW",
        as_instantaneous_events=False,
    )

    assert list(result) == pytest.approx([100.0, 1000.0])


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


def test_collect_flex_config_missing_sensor_raises(fresh_db):
    """Missing flex-model sensor IDs should raise a clear ValueError (GH-2250).

    Previously ``collect_flex_config`` did ``sensor.asset_id`` on a ``None``
    lookup result and raised ``AttributeError: 'NoneType' object has no
    attribute 'asset_id'``. Flex-context already validates via marshmallow;
    flex-model path should match that clarity.
    """
    asset_type = GenericAssetType(name="test-asset-type-missing-sensor")
    fresh_db.session.add(asset_type)
    asset = GenericAsset(
        name="test-asset-missing-sensor", generic_asset_type=asset_type
    )
    fresh_db.session.add(asset)
    fresh_db.session.commit()

    start = datetime(2023, 1, 1, tzinfo=ZoneInfo("UTC"))
    end = start + timedelta(hours=1)
    missing_id = 44207999

    scheduler = StorageScheduler(
        asset_or_sensor=asset,
        start=start,
        end=end,
        resolution=timedelta(hours=1),
        flex_model=[
            {
                "sensor": missing_id,
                "soc-at-start": "4 kWh",
                "roundtrip-efficiency": 0.9,
                "soc-min": "2 kWh",
            }
        ],
        flex_context={},
    )
    with pytest.raises(ValueError, match=f"No sensor found with ID {missing_id}"):
        scheduler.collect_flex_config()

    # Same clarity when resolving asset via state-of-charge sensor reference
    scheduler_soc = StorageScheduler(
        asset_or_sensor=asset,
        start=start,
        end=end,
        resolution=timedelta(hours=1),
        flex_model=[{"state-of-charge": {"sensor": missing_id}}],
        flex_context={},
    )
    with pytest.raises(ValueError, match=f"No sensor found with ID {missing_id}"):
        scheduler_soc.collect_flex_config()


def test_get_power_values_sign_conventions_and_source_filters(fresh_db):
    """The explicit sign convention wins; None defers to the sensor attribute;
    source filters on a SensorReference are honored.

    A single event stores 100 kW from a "scheduler" source (most recent belief) and
    200 kW from a "forecaster" source (an older belief). ``get_power_values`` returns
    MW, normalized to consumption-positive values.
    """
    from flexmeasures.data.models.planning.utils import get_power_values

    query_window = (
        pd.Timestamp("2025-06-01 08:00:00+02:00"),
        pd.Timestamp("2025-06-01 08:15:00+02:00"),
    )
    scheduler_source = DataSource(name="test-scheduler-gpv", type="scheduler")
    forecaster_source = DataSource(name="test-forecaster-gpv", type="forecaster")
    fresh_db.session.add_all([scheduler_source, forecaster_source])

    asset_type = GenericAssetType(name="test-asset-type-gpv")
    fresh_db.session.add(asset_type)
    asset = GenericAsset(name="test-asset-gpv", generic_asset_type=asset_type)
    fresh_db.session.add(asset)
    sensor = Sensor(
        name="test-sensor-gpv",
        generic_asset=asset,
        event_resolution=timedelta(minutes=15),
        unit="kW",
    )
    fresh_db.session.add(sensor)
    fresh_db.session.flush()
    fresh_db.session.add_all(
        [
            TimedBelief(
                event_start=query_window[0],
                belief_horizon=timedelta(0),
                event_value=100.0,
                source=scheduler_source,
                sensor=sensor,
            ),
            TimedBelief(
                event_start=query_window[0],
                belief_horizon=timedelta(hours=1),
                event_value=200.0,
                source=forecaster_source,
                sensor=sensor,
            ),
        ]
    )
    fresh_db.session.commit()

    def series(sensor_or_reference, consumption_is_positive=None):
        return get_power_values(
            query_window=query_window,
            resolution=sensor.event_resolution,
            beliefs_before=None,
            sensor=sensor_or_reference,
            consumption_is_positive=consumption_is_positive,
        )

    # Without source filters, the most recent belief (scheduler, 100 kW) is used.
    # Explicit sign conventions: consumption-positive data passes through,
    # production-positive data is flipped to the consumption-positive convention.
    assert series(sensor, consumption_is_positive=True)[0] == pytest.approx(0.1)
    assert series(sensor, consumption_is_positive=False)[0] == pytest.approx(-0.1)

    # None defers to the sensor's consumption_is_positive attribute (default False)
    assert series(sensor)[0] == pytest.approx(-0.1)
    sensor.attributes = {"consumption_is_positive": True}
    fresh_db.session.commit()
    assert series(sensor)[0] == pytest.approx(0.1)

    # A SensorReference's source filters reach the belief search
    reference = SensorReference(sensor=sensor, exclude_source_types=["scheduler"])
    assert series(reference, consumption_is_positive=True)[0] == pytest.approx(0.2)
    reference = SensorReference(sensor=sensor, source_types=["scheduler"])
    assert series(reference, consumption_is_positive=False)[0] == pytest.approx(-0.1)
