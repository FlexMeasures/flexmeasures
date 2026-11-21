"""Offline regression for energy conversion after report input resampling (#2868)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd
import pytest
import timely_beliefs as tb
from flask import Flask

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.reporting.pandas_reporter import PandasReporter
from flexmeasures.data.models.time_series import Sensor


@pytest.mark.parametrize("input_minutes,report_minutes", [(15, 60), (60, 15), (15, 15)])
def test_reporter_power_to_energy_uses_resampled_input_resolution(
    input_minutes, report_minutes
):
    app = Flask("test_reporter_resolution_conversion")
    app.config["FLEXMEASURES_TIMEZONE"] = "UTC"
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(hours=2)
    source = DataSource(name="test source", type="demo")
    source.id = 1
    asset = GenericAsset(
        name="asset", generic_asset_type=GenericAssetType(name="battery")
    )
    asset.id = 1

    def make_sensor(sensor_id, unit, minutes):
        sensor = Sensor(
            name=f"{unit}_{minutes}m", unit=unit,
            event_resolution=timedelta(minutes=minutes),
            generic_asset=asset, timezone="UTC",
        )
        sensor.id = sensor_id
        return sensor

    input_sensor = make_sensor(1, "kW", input_minutes)
    output_sensor = make_sensor(2, "kWh", report_minutes)
    raw = tb.BeliefsDataFrame([
        tb.TimedBelief(
            sensor=input_sensor,
            source=source,
            event_start=event_start,
            belief_time=start,
            event_value=4.0,
        )
        for event_start in pd.date_range(
            start, periods=120 // input_minutes, freq=f"{input_minutes}min"
        )
    ])
    config = {
        "required_input": [{"name": "power", "unit": "kWh"}],
        "required_output": [{"name": "energy", "unit": "kWh"}],
        "transformations": [
            {"df_input": "power", "df_output": "energy", "method": "copy"}
        ],
    }

    with app.app_context():
        reporter = PandasReporter(config=config, data_source=source)
        reporter._data_source = source

        def search(**criteria):
            resolution = criteria.get("resolution")
            if resolution and resolution != raw.event_resolution:
                return raw.resample_events(
                    resolution, keep_only_most_recent_belief=True
                )
            return raw.copy()

        with patch.object(input_sensor, "search_beliefs", side_effect=search):
            output = reporter._compute_report(
                input=[{"name": "power", "sensor": input_sensor}],
                output=[{"name": "energy", "sensor": output_sensor}],
                start=start, end=end,
                resolution=timedelta(minutes=report_minutes),
            )[0]["data"]

    values = output["event_value"].tolist()
    assert len(values) == 120 // report_minutes
    assert values == pytest.approx([4.0 * report_minutes / 60] * len(values))
    assert sum(values) == pytest.approx(8.0)


def test_reporter_automatic_resolution_uses_actual_resampled_input_period():
    app = Flask("test_reporter_auto_resolution_conversion")
    app.config["FLEXMEASURES_TIMEZONE"] = "UTC"
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    source = DataSource(name="test source", type="demo")
    source.id = 1
    asset = GenericAsset(
        name="asset", generic_asset_type=GenericAssetType(name="battery")
    )
    asset.id = 1

    def make_sensor(sensor_id, unit, minutes):
        s = Sensor(
            name=f"{unit}_{minutes}m", unit=unit,
            event_resolution=timedelta(minutes=minutes),
            generic_asset=asset, timezone="UTC",
        )
        s.id = sensor_id
        return s

    hourly_power = make_sensor(1, "kW", 60)
    quarter_hour_power = make_sensor(2, "kW", 15)
    output_sensor = make_sensor(3, "kWh", 15)

    def beliefs(sensor, minutes):
        return tb.BeliefsDataFrame([
            tb.TimedBelief(
                sensor=sensor, source=source, event_start=t,
                belief_time=start, event_value=4.0
            )
            for t in pd.date_range(
                start, periods=120 // minutes, freq=f"{minutes}min"
            )
        ])

    raw_hourly = beliefs(hourly_power, 60)
    raw_quarter = beliefs(quarter_hour_power, 15)

    config = {
        "required_input": [
            {"name": "power", "unit": "kWh"},
            {"name": "reference"},
        ],
        "required_output": [{"name": "energy", "unit": "kWh"}],
        "transformations": [
            {"df_input": "power", "df_output": "energy", "method": "copy"}
        ],
    }

    def resampled(bdf):
        def search(**criteria):
            resolution = criteria.get("resolution")
            if resolution and resolution != bdf.event_resolution:
                return bdf.resample_events(
                    resolution, keep_only_most_recent_belief=True
                )
            return bdf.copy()
        return search

    with app.app_context():
        reporter = PandasReporter(config=config, data_source=source)
        reporter._data_source = source
        with (
            patch.object(
                hourly_power, "search_beliefs",
                side_effect=resampled(raw_hourly)
            ),
            patch.object(
                quarter_hour_power, "search_beliefs",
                side_effect=resampled(raw_quarter)
            ),
        ):
            result = reporter._compute_report(
                input=[
                    {"name": "power", "sensor": hourly_power},
                    {"name": "reference", "sensor": quarter_hour_power},
                ],
                output=[{"name": "energy", "sensor": output_sensor}],
                start=start,
                end=start + timedelta(hours=2),
                resolution=None,
            )[0]["data"]
    assert result.event_resolution == timedelta(minutes=15)
    assert result["event_value"].tolist() == pytest.approx([1.0] * 8)
    assert sum(result["event_value"]) == pytest.approx(8.0)
