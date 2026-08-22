"""Tests that a chart data window can be fetched in parts.

The asset and sensor pages reuse the data they already hold when the selected time
window changes, and fetch only the parts that are new (see chart-data-cache.js).
That is only sound if asking for [a, b) and [b, c) yields the same beliefs as asking
for [a, c) in one go, which is what these tests pin down.
"""

import json
from datetime import datetime, timedelta

import pytest
from pytz import utc

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor, TimedBelief

WINDOW_START = datetime(2022, 1, 1, tzinfo=utc)


def _chart_values(asset, sensors, start, end) -> dict[tuple[int, int], float]:
    """Return the chart's beliefs for a window, keyed by sensor and event start."""
    payload = json.loads(
        asset.chart_data_json(
            sensors=sensors,
            event_starts_after=start,
            event_ends_before=end,
            compress_json=True,
            most_recent_beliefs_only=True,
        )
    )
    return {(datum["sid"], datum["ts"]): datum["val"] for datum in payload["data"]}


def _asset_with_data(
    db, setup_accounts, setup_sources, resolution: timedelta, days: int, label: str
):
    """Build an asset with one sensor, filled with `days` days of measurements."""
    asset_type = (
        db.session.query(GenericAssetType).filter_by(name="battery").one_or_none()
    )
    if asset_type is None:
        asset_type = GenericAssetType(name="battery")
        db.session.add(asset_type)
        db.session.flush()
    asset = GenericAsset(
        name=f"split test asset ({label})",
        generic_asset_type=asset_type,
        account_id=setup_accounts["Prosumer"].id,
    )
    db.session.add(asset)
    db.session.flush()
    sensor = Sensor(
        name=f"split test sensor ({label})",
        generic_asset=asset,
        event_resolution=resolution,
        unit="MW",
    )
    db.session.add(sensor)
    db.session.flush()
    source = list(setup_sources.values())[0]
    n_events = int(timedelta(days=days) / resolution)
    db.session.bulk_insert_mappings(
        TimedBelief,
        [
            dict(
                event_start=WINDOW_START + resolution * i,
                belief_horizon=timedelta(0),
                event_value=float(i),
                sensor_id=sensor.id,
                source_id=source.id,
                cumulative_probability=0.5,
            )
            for i in range(n_events)
        ],
    )
    asset.sensors_to_show = [{"title": sensor.name, "sensor": sensor.id}]
    db.session.flush()
    return asset


@pytest.mark.parametrize(
    "resolution",
    [
        timedelta(minutes=15),
        timedelta(hours=1),
        timedelta(days=1),
        # A resolution that does not divide a day, so an event straddles the seam.
        timedelta(minutes=7),
    ],
)
def test_split_window_yields_the_same_beliefs(
    db, setup_accounts, setup_sources, resolution
):
    """Fetching a window in two parts loses nothing and invents nothing."""
    from flexmeasures.data.schemas.generic_assets import SensorsToShowSchema

    asset = _asset_with_data(
        db,
        setup_accounts,
        setup_sources,
        resolution,
        days=2,
        label=f"whole vs split {resolution}",
    )
    sensors = SensorsToShowSchema.flatten(asset.validate_sensors_to_show())

    start = WINDOW_START
    seam = WINDOW_START + timedelta(days=1)
    end = WINDOW_START + timedelta(days=2)

    whole = _chart_values(asset, sensors, start, end)
    first_half = _chart_values(asset, sensors, start, seam)
    second_half = _chart_values(asset, sensors, seam, end)
    split = {**first_half, **second_half}

    assert set(split) == set(
        whole
    ), "the split window must cover exactly the same events"
    assert split == whole, "the split window must report the same values"


def test_split_window_may_repeat_an_event_but_never_contradicts_itself(
    db, setup_accounts, setup_sources
):
    """An event straddling the seam is returned on both sides, with the same value.

    That is why the front end de-duplicates the merged records rather than trying to
    fetch strictly non-overlapping ranges.
    """
    from flexmeasures.data.schemas.generic_assets import SensorsToShowSchema

    resolution = timedelta(minutes=7)
    asset = _asset_with_data(
        db, setup_accounts, setup_sources, resolution, days=2, label="seam repeat"
    )
    sensors = SensorsToShowSchema.flatten(asset.validate_sensors_to_show())

    seam = WINDOW_START + timedelta(days=1)
    first_half = _chart_values(asset, sensors, WINDOW_START, seam)
    second_half = _chart_values(asset, sensors, seam, WINDOW_START + timedelta(days=2))

    repeated = set(first_half) & set(second_half)
    assert repeated, "expected the event straddling the seam to appear on both sides"
    for key in repeated:
        assert first_half[key] == second_half[key], "the halves must agree on the value"
