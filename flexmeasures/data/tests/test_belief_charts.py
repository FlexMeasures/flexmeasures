"""Tests for the chart specifications produced for assets that mix real sensors
with fixed-value references from flex_model / flex_context.

The key scenarios checked here:
- SOC sensor + soc-min + soc-max appear in the **same** chart layer (not vconcat'd
  into separate rows).
- Fixed-value sensors receive sequential negative IDs (-1, -2, …).
- When ``include_data=True``, the chart dataset contains records for all three
  "sensors", including the two fixed-value boundaries.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest
import pytz

from flexmeasures import Sensor
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import TimedBelief


@pytest.fixture(scope="function")
def battery_with_soc_flex_model(app, fresh_db):
    """Battery asset (public, no owner) with:

    * A real ``state of charge`` sensor (unit ``kWh``, 15-min resolution).
    * ``soc-min: "20 kWh"`` and ``soc-max: "80 kWh"`` in the flex_model.
    * ``sensors_to_show`` configured so the SOC sensor and both boundaries
      appear together in **one row** (same Vega-Lite layer, not vconcat'd).
    * A handful of SOC beliefs so the real-sensor data path is exercised.
    """
    battery_type = GenericAssetType(name="test_battery_type_for_charts")
    fresh_db.session.add(battery_type)
    fresh_db.session.flush()

    battery = GenericAsset(
        name="Test Battery (chart tests)",
        generic_asset_type=battery_type,
        # Public asset → no owner → no current_user needed in validate_sensors_to_show
        flex_model={
            "soc-min": "20 kWh",
            "soc-max": "80 kWh",
        },
    )
    fresh_db.session.add(battery)
    fresh_db.session.flush()

    soc_sensor = Sensor(
        name="state of charge",
        unit="kWh",
        event_resolution=timedelta(0),  # SOC is an instantaneous measurement
        generic_asset=battery,
    )
    fresh_db.session.add(soc_sensor)
    fresh_db.session.flush()

    # Group SOC + soc-min + soc-max in a single sensors_to_show entry so they
    # end up in the same chart row / Vega-Lite layer.
    battery.sensors_to_show = [
        {
            "title": None,
            "plots": [
                {"sensor": soc_sensor.id},
                {"asset": battery.id, "flex-model": "soc-min"},
                {"asset": battery.id, "flex-model": "soc-max"},
            ],
        }
    ]
    fresh_db.session.flush()

    # Add a day's worth of SOC beliefs so real-sensor records appear in the dataset.
    data_source = DataSource(name="test script", type="demo script")
    fresh_db.session.add(data_source)
    fresh_db.session.flush()

    start = datetime(2015, 1, 1, tzinfo=pytz.utc)
    timestamps = pd.date_range(start, periods=96, freq="15min", tz="UTC")
    for i, ts in enumerate(timestamps):
        fresh_db.session.add(
            TimedBelief(
                sensor=soc_sensor,
                event_start=ts,
                event_value=20.0 + i * 0.5,  # ramps from 20 → ~67.5 kWh
                belief_horizon=timedelta(0),
                source=data_source,
            )
        )
    fresh_db.session.flush()

    return battery, soc_sensor


# ---------------------------------------------------------------------------
# Tests for validate_sensors_to_show
# ---------------------------------------------------------------------------


def test_soc_with_boundaries_in_same_row(battery_with_soc_flex_model):
    """All three sensors (SOC + soc-min + soc-max) must end up in one row."""
    battery, soc_sensor = battery_with_soc_flex_model

    rows = battery.validate_sensors_to_show()

    assert len(rows) == 1, "Expected exactly one chart row (no vconcat split)"

    plots = rows[0]["plots"]
    assert len(plots) == 1

    all_sensors = plots[0]["sensors"]
    assert len(all_sensors) == 3, "Expected SOC + soc-min + soc-max"


def test_fixed_value_sensors_have_sequential_negative_ids(battery_with_soc_flex_model):
    """Fixed-value sensors must receive sequential negative IDs (-1, -2, …)."""
    battery, soc_sensor = battery_with_soc_flex_model

    rows = battery.validate_sensors_to_show()
    all_sensors = rows[0]["plots"][0]["sensors"]

    fixed_value_sensors = [s for s in all_sensors if s.id < 0]
    assert len(fixed_value_sensors) == 2

    ids = sorted(s.id for s in fixed_value_sensors)
    assert ids == [-2, -1], (
        f"Expected sequential IDs [-2, -1], got {ids}. "
        "Fixed-value sensors must be numbered -1, -2, … in order of appearance."
    )


def test_real_sensor_has_positive_id(battery_with_soc_flex_model):
    battery, soc_sensor = battery_with_soc_flex_model
    rows = battery.validate_sensors_to_show()
    all_sensors = rows[0]["plots"][0]["sensors"]

    real_sensors = [s for s in all_sensors if s.id >= 0]
    assert len(real_sensors) == 1
    assert real_sensors[0].id == soc_sensor.id


# ---------------------------------------------------------------------------
# Tests for chart() and chart_data_json()
# ---------------------------------------------------------------------------


def test_chart_has_one_vconcat_row(battery_with_soc_flex_model):
    """The chart spec must contain exactly one vconcat row."""
    battery, _ = battery_with_soc_flex_model

    start = datetime(2015, 1, 1, tzinfo=pytz.utc)
    end = datetime(2015, 1, 2, tzinfo=pytz.utc)

    spec = battery.chart(
        include_data=False,
        event_starts_after=start,
        event_ends_before=end,
    )

    assert "vconcat" in spec
    assert len(spec["vconcat"]) == 1, (
        "Expected one vconcat row for SOC + boundaries together, "
        f"got {len(spec['vconcat'])}"
    )


def test_chart_data_includes_all_three_sensors(battery_with_soc_flex_model):
    """The chart dataset must contain records for the real SOC sensor and both
    fixed-value boundaries (soc-min and soc-max)."""
    battery, soc_sensor = battery_with_soc_flex_model

    start = datetime(2015, 1, 1, tzinfo=pytz.utc)
    end = datetime(2015, 1, 2, tzinfo=pytz.utc)

    spec = battery.chart(
        include_data=True,
        event_starts_after=start,
        event_ends_before=end,
    )

    dataset_name = f"asset_{battery.id}"
    assert dataset_name in spec["datasets"]

    records = spec["datasets"][dataset_name]
    assert records, "Dataset must not be empty"

    sensor_ids_present = {r["sensor"]["id"] for r in records}

    # Real sensor
    assert (
        soc_sensor.id in sensor_ids_present
    ), f"Real SOC sensor (id={soc_sensor.id}) missing from dataset"

    # Fixed-value sensors
    assert -1 in sensor_ids_present, "soc-min (id=-1) missing from dataset"
    assert -2 in sensor_ids_present, "soc-max (id=-2) missing from dataset"


def test_fixed_value_records_have_correct_constant_values(battery_with_soc_flex_model):
    """soc-min records must all equal 20 kWh; soc-max records must all equal 80 kWh."""
    battery, _ = battery_with_soc_flex_model

    start = datetime(2015, 1, 1, tzinfo=pytz.utc)
    end = datetime(2015, 1, 2, tzinfo=pytz.utc)

    spec = battery.chart(
        include_data=True,
        event_starts_after=start,
        event_ends_before=end,
    )

    records = spec["datasets"][f"asset_{battery.id}"]

    soc_min_records = [r for r in records if r["sensor"]["id"] == -1]
    soc_max_records = [r for r in records if r["sensor"]["id"] == -2]

    assert soc_min_records, "No records found for soc-min (id=-1)"
    assert soc_max_records, "No records found for soc-max (id=-2)"

    assert all(
        r["event_value"] == 20.0 for r in soc_min_records
    ), "soc-min records must all have event_value=20.0"
    assert all(
        r["event_value"] == 80.0 for r in soc_max_records
    ), "soc-max records must all have event_value=80.0"


def test_fixed_value_sensor_unit_matches_flex_model(battery_with_soc_flex_model):
    """Fixed-value sensor records must carry the unit specified in the flex_model."""
    battery, _ = battery_with_soc_flex_model

    start = datetime(2015, 1, 1, tzinfo=pytz.utc)
    end = datetime(2015, 1, 2, tzinfo=pytz.utc)

    spec = battery.chart(
        include_data=True,
        event_starts_after=start,
        event_ends_before=end,
    )

    records = spec["datasets"][f"asset_{battery.id}"]

    for sensor_id in (-1, -2):
        for record in (r for r in records if r["sensor"]["id"] == sensor_id):
            assert record["sensor_unit"] == "kWh", (
                f"sensor_unit for fixed-value sensor {sensor_id} should be 'kWh', "
                f"got {record['sensor_unit']!r}"
            )


# ---------------------------------------------------------------------------
# Tests for the UI path: chart_data_json(compress_json=True)
#
# The asset page → Graphs view always fetches
#   GET /api/v3_0/assets/<id>/chart_data?compress_json=true
# which calls asset.chart_data_json(compress_json=True, ...).
# The compress_json format returns {"data": [...], "sensors": {...},
# "sources": {...}} instead of a plain list.  These tests guard against
# the AttributeError: 'dict' object has no attribute 'extend' regression
# that occurred when fixed-value sensors were present.
# ---------------------------------------------------------------------------


def test_chart_data_json_compressed_does_not_crash(battery_with_soc_flex_model):
    """chart_data_json with compress_json=True must not raise for an asset that
    has fixed-value sensors — this is the exact code path the Graphs view uses."""
    battery, _ = battery_with_soc_flex_model

    start = datetime(2015, 1, 1, tzinfo=pytz.utc)
    end = datetime(2015, 1, 2, tzinfo=pytz.utc)

    # Must not raise AttributeError: 'dict' object has no attribute 'extend'
    result = battery.chart_data_json(
        compress_json=True,
        event_starts_after=start,
        event_ends_before=end,
    )
    assert isinstance(result, str), "chart_data_json must return a JSON string"


def test_chart_data_json_compressed_returns_expected_structure(
    battery_with_soc_flex_model,
):
    """The compressed response must have the three top-level keys expected by
    the front-end: ``data``, ``sensors``, and ``sources``."""
    battery, _ = battery_with_soc_flex_model

    start = datetime(2015, 1, 1, tzinfo=pytz.utc)
    end = datetime(2015, 1, 2, tzinfo=pytz.utc)

    import json

    parsed = json.loads(
        battery.chart_data_json(
            compress_json=True,
            event_starts_after=start,
            event_ends_before=end,
        )
    )

    assert "data" in parsed, "Compressed response must contain 'data' key"
    assert "sensors" in parsed, "Compressed response must contain 'sensors' key"
    assert "sources" in parsed, "Compressed response must contain 'sources' key"


def test_chart_data_json_compressed_includes_fixed_value_sensors(
    battery_with_soc_flex_model,
):
    """Fixed-value sensor records (soc-min, soc-max) must appear in the
    compressed ``data`` list and their metadata must be in ``sensors``."""
    battery, soc_sensor = battery_with_soc_flex_model

    start = datetime(2015, 1, 1, tzinfo=pytz.utc)
    end = datetime(2015, 1, 2, tzinfo=pytz.utc)

    import json

    parsed = json.loads(
        battery.chart_data_json(
            compress_json=True,
            event_starts_after=start,
            event_ends_before=end,
        )
    )

    sensor_ids_in_data = {r["sid"] for r in parsed["data"]}
    assert -1 in sensor_ids_in_data, "soc-min (sid=-1) missing from compressed data"
    assert -2 in sensor_ids_in_data, "soc-max (sid=-2) missing from compressed data"

    # Metadata entries must be present (keyed by string id)
    assert "-1" in parsed["sensors"], "Sensor metadata for soc-min (-1) missing"
    assert "-2" in parsed["sensors"], "Sensor metadata for soc-max (-2) missing"


def test_chart_data_json_compressed_fixed_value_records_are_correct(
    battery_with_soc_flex_model,
):
    """Fixed-value records in the compressed format must carry the right
    constant values (20.0 for soc-min, 80.0 for soc-max) and a source reference."""
    battery, _ = battery_with_soc_flex_model

    start = datetime(2015, 1, 1, tzinfo=pytz.utc)
    end = datetime(2015, 1, 2, tzinfo=pytz.utc)

    import json

    parsed = json.loads(
        battery.chart_data_json(
            compress_json=True,
            event_starts_after=start,
            event_ends_before=end,
        )
    )

    soc_min_records = [r for r in parsed["data"] if r["sid"] == -1]
    soc_max_records = [r for r in parsed["data"] if r["sid"] == -2]

    assert soc_min_records, "No records for soc-min (sid=-1)"
    assert soc_max_records, "No records for soc-max (sid=-2)"

    assert all(
        r["val"] == 20.0 for r in soc_min_records
    ), "soc-min compressed records must all have val=20.0"
    assert all(
        r["val"] == 80.0 for r in soc_max_records
    ), "soc-max compressed records must all have val=80.0"

    # Each record must reference a source
    for r in soc_min_records + soc_max_records:
        assert "src" in r, "Compressed fixed-value record must carry a 'src' key"


def test_chart_data_json_compressed_source_references_flex_model(
    battery_with_soc_flex_model,
):
    """The source metadata for fixed-value sensors must indicate that the value
    originated from the flex-model (not just say 'Reference' with no context)."""
    battery, _ = battery_with_soc_flex_model

    start = datetime(2015, 1, 1, tzinfo=pytz.utc)
    end = datetime(2015, 1, 2, tzinfo=pytz.utc)

    import json

    parsed = json.loads(
        battery.chart_data_json(
            compress_json=True,
            event_starts_after=start,
            event_ends_before=end,
        )
    )

    # At least one source entry should mention 'flex-model'
    source_descriptions = [v.get("description", "") for v in parsed["sources"].values()]
    assert any("flex-model" in d for d in source_descriptions), (
        "Source metadata must reference 'flex-model' for values from the flex_model; "
        f"got descriptions: {source_descriptions}"
    )


def test_chart_data_json_skips_invalid_saved_asset_reference(
    battery_with_soc_flex_model,
):
    """Invalid saved flex references should be ignored instead of crashing chart endpoints."""
    battery, soc_sensor = battery_with_soc_flex_model

    # Keep one valid sensor plot and add one invalid flex-context reference.
    battery.sensors_to_show = [
        {
            "title": "Mixed",
            "plots": [
                {"sensor": soc_sensor.id},
                {"asset": battery.id, "flex-context": "non-existing-field"},
            ],
        }
    ]

    start = datetime(2015, 1, 1, tzinfo=pytz.utc)
    end = datetime(2015, 1, 2, tzinfo=pytz.utc)

    import json

    parsed = json.loads(
        battery.chart_data_json(
            compress_json=True,
            event_starts_after=start,
            event_ends_before=end,
        )
    )

    sensor_ids_in_data = {r["sid"] for r in parsed["data"]}
    assert soc_sensor.id in sensor_ids_in_data
    assert -1 not in sensor_ids_in_data
