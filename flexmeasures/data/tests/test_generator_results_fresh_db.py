"""Checking and saving what a data generator returns, the same way for every kind of generator (#2682)."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest
import timely_beliefs as tb
from sqlalchemy import func, select

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.services import generator_results
from flexmeasures.data.services.generator_results import (
    GeneratorWritesUncheckedSensor,
    check_generator_results,
    save_generator_results,
)


def test_a_refused_output_is_not_mistaken_for_an_operating_system_error():
    """The refusal names the generator, the refused sensors and the permitted ones, and keeps them as attributes.

    It is no PermissionError, which is the operating system's (an OSError),
    so that it cannot be mistaken for a file that could not be written, nor caught by handlers of I/O errors.
    """
    refusal = GeneratorWritesUncheckedSensor(
        "StorageScheduler (data source 4)", [12, 11, 12], {3, 1}, automation_id=7
    )

    assert not isinstance(refusal, OSError)
    assert refusal.generator == "StorageScheduler (data source 4)"
    assert refusal.refused_sensor_ids == [11, 12]
    assert refusal.permitted_sensor_ids == [1, 3]
    assert refusal.automation_id == 7
    assert str(refusal) == (
        "StorageScheduler (data source 4) would record data on sensor(s) 11, 12,"
        " which are not among the sensors automation 7 was checked against when it was created (1, 3)."
    )
    assert "which are not among the sensors it may record on (none)." in str(
        GeneratorWritesUncheckedSensor("PandasReporter", [5], [])
    )


class _Sensor:
    def __init__(self, sensor_id: int):
        self.id = sensor_id


def test_results_are_judged_as_a_whole_and_those_without_a_sensor_are_not_judged():
    """Every refused sensor is named at once, and a result recording on no sensor is let through."""
    results = [
        {"sensor": _Sensor(1)},
        {"sensor": _Sensor(8)},
        {"sensor": _Sensor(9)},
        {"name": "scheduling_result"},  # bookkeeping, recording on no sensor
    ]
    with pytest.raises(GeneratorWritesUncheckedSensor) as refusal:
        check_generator_results(results, {1}, "a generator")
    assert refusal.value.refused_sensor_ids == [8, 9]

    # No permitted set means no check applies, as on the trusted CLI.
    check_generator_results(results, None, "a generator")


@pytest.fixture
def two_outputs(fresh_db):
    asset_type = GenericAssetType(name="site")
    asset = GenericAsset(name="site", generic_asset_type=asset_type)
    sensors = [
        Sensor(
            name=f"output {i}",
            generic_asset=asset,
            event_resolution=timedelta(hours=1),
            unit="MW",
        )
        for i in (1, 2)
    ]
    source = DataSource(name="a generator", type="reporter")
    fresh_db.session.add_all([asset_type, asset, *sensors, source])
    fresh_db.session.commit()
    results = [
        {
            "sensor": sensor,
            "data": tb.BeliefsDataFrame(
                [
                    tb.TimedBelief(
                        sensor=sensor,
                        source=source,
                        event_start=pd.Timestamp("2026-01-01T05:00:00+00:00")
                        + i * sensor.event_resolution,
                        belief_time=pd.Timestamp("2026-01-01T00:00:00+00:00"),
                        event_value=float(i),
                    )
                    for i in range(3)
                ]
            ),
        }
        for sensor in sensors
    ]
    return results


def _beliefs_in_session(db) -> int:
    return db.session.scalar(select(func.count()).select_from(TimedBelief))


def test_a_save_that_fails_halfway_leaves_nothing_staged(
    fresh_db, two_outputs, monkeypatch
):
    """If the second of two outputs fails to save, the first is not left staged, and the session stays usable.

    Without a savepoint, the first output's flushed beliefs would stay in the session,
    where a later commit in the same process could record half a run.
    """
    real_save = generator_results.save_to_db_and_count
    saves = []

    def fail_on_second_save(data, **kwargs):
        saves.append(data)
        if len(saves) > 1:
            raise RuntimeError("database gone")
        return real_save(data, **kwargs)

    monkeypatch.setattr(generator_results, "save_to_db_and_count", fail_on_second_save)
    before = _beliefs_in_session(fresh_db)

    with pytest.raises(RuntimeError, match="database gone"):
        save_generator_results(two_outputs)

    assert len(saves) == 2, "the first output really was saved before the failure"
    assert _beliefs_in_session(fresh_db) == before


def test_saving_results_counts_what_was_saved_and_repeats_nothing(
    fresh_db, two_outputs
):
    """Each result says how many beliefs it saved, and saving the same results again saves none of them."""
    first = save_generator_results(two_outputs)
    fresh_db.session.commit()
    again = save_generator_results(two_outputs)
    fresh_db.session.commit()

    assert [entry["n_rows"] for entry in first] == [3, 3]
    assert [entry["n_rows"] for entry in again] == [0, 0]
    assert _beliefs_in_session(fresh_db) == 6
