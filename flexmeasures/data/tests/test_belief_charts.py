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

import json
from datetime import datetime, timedelta

import pandas as pd
import pytest
import pytz

from flexmeasures import Sensor
from flexmeasures.data.models.charts.utils import source_legend_label_transformation
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.time_series import TimedBelief


def _walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _collect_scenegraph_texts(value) -> list[str]:
    texts = []
    if isinstance(value, dict):
        if "text" in value:
            texts.append(value["text"])
        for child in value.values():
            texts.extend(_collect_scenegraph_texts(child))
    elif isinstance(value, list):
        for child in value:
            texts.extend(_collect_scenegraph_texts(child))
    return texts


def _chart_source(
    source_id: int,
    name: str,
    display_type: str,
    source_type: str = "other",
    model: str = "",
    version: str = "",
    raw_type: str | None = None,
) -> dict:
    return {
        "source": {
            "id": source_id,
            "name": name,
            "display_type": display_type,
            "raw_type": raw_type or display_type,
            "type": source_type,
            "model": model,
            "version": version,
        }
    }


def _render_source_legend_labels(values: list[dict]) -> list[str]:
    vl_convert = pytest.importorskip("vl_convert")
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "data": {"values": values},
        "transform": source_legend_label_transformation,
        "mark": "text",
        "encoding": {
            "text": {"field": "source_legend_label", "type": "nominal"},
            "y": {"field": "source.id", "type": "nominal", "axis": None},
        },
    }
    return _collect_scenegraph_texts(vl_convert.vegalite_to_scenegraph(spec))


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


def test_bar_chart_uses_source_legend_label_with_id_fallback(
    battery_with_soc_flex_model,
):
    """Duplicate source-name labels should use IDs only as a last resort."""
    _, soc_sensor = battery_with_soc_flex_model

    start = datetime(2015, 1, 1, tzinfo=pytz.utc)
    end = datetime(2015, 1, 2, tzinfo=pytz.utc)

    spec = soc_sensor.chart(
        include_data=False,
        event_starts_after=start,
        event_ends_before=end,
    )
    data_layer = spec["layer"][0]
    transforms = data_layer["transform"]

    assert data_layer["encoding"]["color"]["field"] == "source_legend_label"
    assert (
        data_layer["encoding"]["stroke"]["condition"]["field"] == "source_legend_label"
    )
    display_type_transform = next(
        transform
        for transform in transforms
        if transform.get("as") == "source_display_type"
    )
    assert "source.display_type" in display_type_transform["calculate"]
    assert "source.raw_type" in display_type_transform["calculate"]
    assert any(
        transform.get("as") == "source_version_detail"
        and "source.version" in transform["calculate"]
        for transform in transforms
    )

    legend_label_transform = next(
        transform
        for transform in transforms
        if transform.get("as") == "source_legend_label"
    )
    assert "ID:" in legend_label_transform["calculate"]
    assert "source.id" in legend_label_transform["calculate"]

    tooltip_id_transform = next(
        transform
        for transform in transforms
        if transform.get("as") == "source_name_and_id"
    )
    assert "ID:" in tooltip_id_transform["calculate"]
    tooltip_fields = [
        tooltip["field"]
        for tooltip in data_layer["encoding"]["tooltip"]
        if tooltip is not None
    ]
    assert "source_name_and_id" in tooltip_fields
    assert "source.display_type" in tooltip_fields
    assert "source.model" in tooltip_fields
    assert "source.version" in tooltip_fields


def test_source_legend_label_transform_renders_short_non_id_labels():
    values = [
        _chart_source(1, "Unique", "user"),
        _chart_source(
            2,
            "FlexMeasures",
            "forecaster",
            source_type="forecaster",
            model="TrainPredictPipeline",
            version="1",
        ),
        _chart_source(
            3, "FlexMeasures", "reporter", model="PandasReporter", version="1"
        ),
        _chart_source(4, "Seita", "reporter", model="ModelA", version="1"),
        _chart_source(5, "Seita", "reporter", model="ModelB", version="1"),
        _chart_source(6, "Acme", "reporter", model="Shared", version="1"),
        _chart_source(7, "Acme", "reporter", model="Shared", version="2"),
    ]
    texts = _render_source_legend_labels(values)

    assert texts == [
        "Unique",
        "FlexMeasures (forecaster)",
        "FlexMeasures (reporter)",
        "Seita (ModelA)",
        "Seita (ModelB)",
        "Acme (v1)",
        "Acme (v2)",
    ]
    assert "(" not in texts[0]
    assert all("(" in text and ")" in text for text in texts[1:])
    assert all("ID:" not in text for text in texts)


def test_source_legend_label_transform_handles_sparse_source_metadata():
    texts = _render_source_legend_labels(
        [
            _chart_source(1, "NoModel", "reporter", model="", version="1"),
            _chart_source(2, "NoModel", "reporter", model="", version="2"),
            _chart_source(
                3,
                "ModelOnly",
                "",
                source_type="",
                raw_type="",
                model="ModelA",
            ),
            _chart_source(
                4,
                "ModelOnly",
                "",
                source_type="",
                raw_type="",
                model="ModelB",
            ),
            {
                "source": {
                    "id": 5,
                    "name": "OldData",
                    "type": "scheduler",
                    "model": "",
                    "version": "",
                }
            },
            {
                "source": {
                    "id": 6,
                    "name": "OldData",
                    "type": "other",
                    "model": "",
                    "version": "",
                }
            },
            _chart_source(7, "NoDetails", "", source_type="", raw_type=""),
            _chart_source(8, "NoDetails", "", source_type="", raw_type=""),
        ]
    )

    assert texts == [
        "NoModel (v1)",
        "NoModel (v2)",
        "ModelOnly (ModelA)",
        "ModelOnly (ModelB)",
        "OldData (scheduler)",
        "OldData (other)",
        "NoDetails (ID: 7)",
        "NoDetails (ID: 8)",
    ]
    assert all("undefined" not in text for text in texts)
    assert all("()" not in text for text in texts)
    assert all("ID:" not in text for text in texts[:-2])


def test_chart_styling_still_uses_normalized_source_type(battery_with_soc_flex_model):
    """The new label field must not replace source.type for visual styling."""
    battery, _ = battery_with_soc_flex_model

    start = datetime(2015, 1, 1, tzinfo=pytz.utc)
    end = datetime(2015, 1, 2, tzinfo=pytz.utc)

    spec = battery.chart(
        include_data=False,
        event_starts_after=start,
        event_ends_before=end,
    )
    stroke_dash_encodings = [
        node["strokeDash"]
        for node in _walk_dicts(spec)
        if isinstance(node.get("strokeDash"), dict)
    ]

    assert any(
        stroke_dash.get("field") == "source.type"
        and stroke_dash.get("scale", {}).get("domain")
        == ["forecaster", "scheduler", "other"]
        for stroke_dash in stroke_dash_encodings
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


def test_chart_data_json_preserves_display_source_type_for_labels(
    battery_with_soc_flex_model,
    fresh_db,
):
    """Chart data should preserve exact and label-friendly source type metadata."""
    battery, soc_sensor = battery_with_soc_flex_model
    start = datetime(2015, 1, 1, tzinfo=pytz.utc)
    end = datetime(2015, 1, 2, tzinfo=pytz.utc)

    forecaster_source = DataSource(
        name="FlexMeasures",
        type="forecaster",
        model="TrainPredictPipeline",
        version="1",
    )
    reporter_source = DataSource(
        name="FlexMeasures",
        type="reporter",
        model="PandasReporter",
        version="1",
    )
    fresh_db.session.add_all([forecaster_source, reporter_source])
    fresh_db.session.flush()

    for source, value in [(forecaster_source, 31), (reporter_source, 32)]:
        fresh_db.session.add(
            TimedBelief(
                sensor=soc_sensor,
                event_start=start,
                event_value=value,
                belief_horizon=timedelta(0),
                source=source,
            )
        )
    fresh_db.session.flush()

    parsed = json.loads(
        battery.chart_data_json(
            compress_json=True,
            event_starts_after=start,
            event_ends_before=end,
        )
    )

    forecaster_metadata = parsed["sources"][str(forecaster_source.id)]
    assert forecaster_metadata["type"] == "forecaster"
    assert forecaster_metadata["raw_type"] == "forecaster"
    assert forecaster_metadata["display_type"] == "forecaster"
    assert forecaster_metadata["model"] == "TrainPredictPipeline"
    assert forecaster_metadata["version"] == "1"

    reporter_metadata = parsed["sources"][str(reporter_source.id)]
    assert reporter_metadata["type"] == "other"
    assert reporter_metadata["raw_type"] == "reporter"
    assert reporter_metadata["display_type"] == "reporter"
    assert reporter_metadata["model"] == "PandasReporter"
    assert reporter_metadata["version"] == "1"


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

    parsed = json.loads(
        battery.chart_data_json(
            compress_json=True,
            event_starts_after=start,
            event_ends_before=end,
        )
    )

    sensor_ids_in_data = {r["sid"] for r in parsed["data"]}
    assert soc_sensor.id in sensor_ids_in_data


# ---------------------------------------------------------------------------
# Tests for the `y-axis` option (per-sub-chart y-axis domain selection)
# ---------------------------------------------------------------------------


def _find_y_scale(spec: dict) -> dict | None:
    """Dig out encoding.y.scale from the first layer of the first vconcat row."""
    row = spec["vconcat"][0]
    layers = row.get("layer", [row])
    for layer in layers:
        encoding = layer.get("encoding", {})
        y = encoding.get("y")
        if y and "scale" in y:
            return y["scale"]
    return None


def test_setup_event_value_field_y_axis_data_forces_zero_false():
    from flexmeasures.data.models.charts.belief_charts import (
        _setup_event_value_field,
    )

    field = _setup_event_value_field("power", "kW", y_axis="data")
    assert field["scale"] == {"zero": False}


def test_setup_event_value_field_y_axis_range_sets_domain_as_floor():
    """A [min, max] y-axis is a floor (unionWith), not a hard clip: the spec
    does not hard-bound the axis, it only guarantees it covers at least
    the given range and expands to fit data beyond it."""
    from flexmeasures.data.models.charts.belief_charts import (
        _setup_event_value_field,
    )

    field = _setup_event_value_field("power", "kW", y_axis=[10, 20])
    assert field["scale"] == {"domain": {"unionWith": [10, 20]}, "nice": False}
    # Not a hard/bare domain list - that would clip the data.
    assert field["scale"]["domain"] != [10, 20]


def test_setup_event_value_field_y_axis_absent_default_padded():
    from flexmeasures.data.models.charts.belief_charts import (
        _setup_event_value_field,
    )

    field = _setup_event_value_field("power", "kW")
    assert field.get("scale", {}).get("zero") is not False


def test_setup_event_value_field_percent_default_gets_domain():
    from flexmeasures.data.models.charts.belief_charts import (
        _setup_event_value_field,
    )

    field = _setup_event_value_field("state of charge", "%")
    assert field["scale"] == {"domain": {"unionWith": [0, 105]}, "nice": False}


def test_setup_event_value_field_percent_y_axis_data_drops_domain():
    from flexmeasures.data.models.charts.belief_charts import (
        _setup_event_value_field,
    )

    field = _setup_event_value_field("state of charge", "%", y_axis="data")
    assert field["scale"] == {"zero": False}


def test_setup_event_value_field_percent_y_axis_range_overrides_domain():
    from flexmeasures.data.models.charts.belief_charts import (
        _setup_event_value_field,
    )

    field = _setup_event_value_field("state of charge", "%", y_axis=[0, 50])
    assert field["scale"] == {"domain": {"unionWith": [0, 50]}, "nice": False}


def test_chart_y_scale_zero_false_when_entry_opts_in(
    battery_with_soc_flex_model,
):
    battery, soc_sensor = battery_with_soc_flex_model

    battery.sensors_to_show = [
        {
            "title": None,
            "y-axis": "data",
            "plots": [
                {"sensor": soc_sensor.id},
                {
                    "asset": battery.id,
                    "flex-model": "soc-min",
                },
                {
                    "asset": battery.id,
                    "flex-model": "soc-max",
                },
            ],
        }
    ]

    start = datetime(2015, 1, 1, tzinfo=pytz.utc)
    end = datetime(2015, 1, 2, tzinfo=pytz.utc)

    spec = battery.chart(
        include_data=False, event_starts_after=start, event_ends_before=end
    )

    scale = _find_y_scale(spec)
    assert scale == {"zero": False}


def test_chart_y_scale_domain_when_entry_has_fixed_range(
    battery_with_soc_flex_model,
):
    battery, soc_sensor = battery_with_soc_flex_model

    battery.sensors_to_show = [
        {
            "title": None,
            "y-axis": [10, 90],
            "plots": [
                {"sensor": soc_sensor.id},
            ],
        }
    ]

    start = datetime(2015, 1, 1, tzinfo=pytz.utc)
    end = datetime(2015, 1, 2, tzinfo=pytz.utc)

    spec = battery.chart(
        include_data=False, event_starts_after=start, event_ends_before=end
    )

    scale = _find_y_scale(spec)
    assert scale == {"domain": {"unionWith": [10, 90]}, "nice": False}


def test_chart_y_scale_default_when_y_axis_absent(
    battery_with_soc_flex_model,
):
    battery, _ = battery_with_soc_flex_model

    start = datetime(2015, 1, 1, tzinfo=pytz.utc)
    end = datetime(2015, 1, 2, tzinfo=pytz.utc)

    spec = battery.chart(
        include_data=False, event_starts_after=start, event_ends_before=end
    )

    scale = _find_y_scale(spec)
    assert scale is None or scale.get("zero") is not False


def test_validate_sensors_to_show_propagates_y_axis(
    battery_with_soc_flex_model,
):
    battery, soc_sensor = battery_with_soc_flex_model

    battery.sensors_to_show = [
        {
            "title": None,
            "y-axis": "data",
            "plots": [
                {"sensor": soc_sensor.id},
            ],
        }
    ]

    rows = battery.validate_sensors_to_show()
    assert len(rows) == 1
    assert rows[0]["y-axis"] == "data"


def test_validate_sensors_to_show_omits_y_axis_by_default(
    battery_with_soc_flex_model,
):
    battery, soc_sensor = battery_with_soc_flex_model

    rows = battery.validate_sensors_to_show()
    assert len(rows) == 1
    assert "y-axis" not in rows[0]
