"""Findings that a data generator returns as annotations, saved as versions of them, as beliefs are."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest
from marshmallow import fields
from sqlalchemy import select

from flexmeasures.data.models.annotations import Annotation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.reporting import Reporter
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.schemas.io import Output
from flexmeasures.data.schemas.reporting import ReporterParametersSchema
from flexmeasures.data.services.data_generators import resolve_data_generator_sensors
from flexmeasures.data.services.generator_results import (
    GeneratorWritesUncheckedSensor,
    check_generator_results,
    outputs_of_job_result,
    save_generator_results,
)

WINDOW = (
    pd.Timestamp("2026-11-12T00:00:00+01:00"),
    pd.Timestamp("2026-11-12T12:00:00+01:00"),
)
RUN = pd.Timestamp("2026-11-12T12:00:00+01:00")


def at(time: str) -> pd.Timestamp:
    return pd.Timestamp(f"2026-11-12T{time}:00+01:00")


@pytest.fixture
def meter(fresh_db) -> dict:
    asset_type = GenericAssetType(name="site")
    asset = GenericAsset(name="site", generic_asset_type=asset_type)
    sensor = Sensor(
        name="meter",
        generic_asset=asset,
        event_resolution=timedelta(minutes=15),
        unit="kW",
        timezone="Europe/Amsterdam",
    )
    source = DataSource(name="gap check", type="reporter")
    other_source = DataSource(name="another check", type="reporter")
    fresh_db.session.add_all([asset_type, asset, sensor, source, other_source])
    fresh_db.session.commit()
    return dict(sensor=sensor, source=source, other_source=other_source)


def finding(start: str, end: str, annotation_type: str = "warning") -> dict:
    return dict(
        start=at(start),
        end=at(end),
        type=annotation_type,
        content=f"No data since {start}",
    )


def check(meter, *findings, belief_time=RUN, window=WINDOW) -> int:
    """Save one run's findings on the meter, as a data generator's result, and return how many versions were saved."""
    [saved] = save_generator_results(
        [
            dict(
                kind="annotations",
                subject=meter["sensor"],
                source=meter["source"],
                window=window,
                belief_time=belief_time,
                annotations=list(findings),
            )
        ]
    )
    return saved["n_rows"]


def current(meter, **kwargs) -> list[tuple[str, str, str, str]]:
    """The most recent version of each finding on the meter, as (start, end, type, content)."""
    return sorted(
        (
            a.start.astimezone(WINDOW[0].tz).strftime("%H:%M"),
            a.end.astimezone(WINDOW[0].tz).strftime("%H:%M"),
            a.type,
            a.content,
        )
        for a in meter["sensor"].search_annotations(
            most_recent_beliefs_only=True, **kwargs
        )
    )


# ― Showing only the most recent version ――――――――――――――――――――――――――――――――――――――――――――――――――


def annotate(meter, start, end, annotation_type, belief_time, source=None):
    meter["sensor"].annotations.append(
        Annotation(
            start=at(start),
            end=at(end),
            type=annotation_type,
            content=f"{annotation_type} from {start}",
            belief_time=belief_time,
            source=source or meter["source"],
        )
    )


def test_only_the_most_recent_version_of_an_annotation_is_shown(meter, fresh_db):
    """An annotation is identified by its subject, source and start, so these are three versions of one, plus one of another source."""
    annotate(meter, "03:00", "04:00", "warning", at("04:00"))
    annotate(meter, "03:00", "06:00", "alert", at("06:00"))
    annotate(meter, "03:00", "05:00", "label", at("08:00"))
    annotate(meter, "03:00", "04:00", "warning", at("04:00"), meter["other_source"])
    fresh_db.session.flush()

    assert current(meter) == [
        ("03:00", "04:00", "warning", "warning from 03:00"),
        ("03:00", "05:00", "label", "label from 03:00"),
    ]
    # Without opting in, every version is returned, as before
    assert len(meter["sensor"].search_annotations()) == 4
    # Replaying an earlier moment shows the version known then
    assert current(meter, beliefs_before=at("07:00"), source=meter["source"]) == [
        ("03:00", "06:00", "alert", "alert from 03:00")
    ]
    # The window is applied after the most recent version is picked,
    # so an older version reaching into the window does not show when the most recent one does not
    assert current(meter, annotations_after=at("05:30")) == []


def test_without_belief_times_the_last_recorded_version_counts(meter, fresh_db):
    annotate(meter, "03:00", "04:00", "label", None)
    annotate(meter, "03:00", "05:00", "label", None)
    fresh_db.session.flush()
    assert current(meter) == [("03:00", "05:00", "label", "label from 03:00")]

    # A version with a belief time is more recent than one without
    annotate(meter, "03:00", "06:00", "warning", at("01:00"))
    fresh_db.session.flush()
    assert current(meter) == [("03:00", "06:00", "warning", "warning from 03:00")]


def test_an_asset_search_picks_the_most_recent_version_before_the_type(meter, fresh_db):
    """An alert that was resolved is no alert any more, even though an older version of it was."""
    asset = meter["sensor"].generic_asset
    for annotation_type, belief_time in (
        ("alert", at("04:00")),
        ("label", at("05:00")),
    ):
        asset.annotations.append(
            Annotation(
                start=at("03:00"),
                end=at("04:00"),
                type=annotation_type,
                content=annotation_type,
                belief_time=belief_time,
                source=meter["source"],
            )
        )
    fresh_db.session.flush()

    assert asset.search_annotations(annotation_type="alert") != []
    assert (
        asset.search_annotations(annotation_type="alert", most_recent_beliefs_only=True)
        == []
    )


# ― Saving findings as versions ――――――――――――――――――――――――――――――――――――――――――――――――――――――――――


def test_a_finding_is_saved_once_and_again_when_it_changes(meter):
    assert check(meter, finding("03:15", "05:45")) == 1
    # Unchanged, as on the next run, so nothing new is recorded
    assert (
        check(meter, finding("03:15", "05:45"), belief_time=RUN + timedelta(minutes=15))
        == 0
    )
    # It grew and escalated
    assert (
        check(
            meter,
            finding("03:15", "12:00", "alert"),
            belief_time=RUN + timedelta(hours=1),
        )
        == 1
    )

    assert current(meter) == [("03:15", "12:00", "alert", "No data since 03:15")]
    assert len(meter["sensor"].search_annotations()) == 2


def test_a_finding_the_data_filled_is_resolved(meter):
    check(meter, finding("03:15", "05:45"))

    assert check(meter, belief_time=RUN + timedelta(hours=1)) == 1
    assert current(meter) == [
        ("03:15", "05:45", "label", "Resolved: No data since 03:15")
    ]
    # A resolved finding stays resolved
    assert check(meter, belief_time=RUN + timedelta(hours=2)) == 0


def test_a_partly_filled_finding_splits(meter):
    """Data for 04:00-04:30 arrives inside a 03:15-05:45 gap."""
    check(meter, finding("03:15", "05:45"))

    assert (
        check(
            meter,
            finding("03:15", "04:00"),
            finding("04:30", "05:45"),
            belief_time=RUN + timedelta(hours=1),
        )
        == 2
    )

    # Nothing marks 04:00-04:30 as resolved, as that piece was never a finding of its own
    assert current(meter) == [
        ("03:15", "04:00", "warning", "No data since 03:15"),
        ("04:30", "05:45", "warning", "No data since 04:30"),
    ]
    # The backfill stays visible in the history
    assert ("03:15", "05:45") in {
        (
            a.start.astimezone(WINDOW[0].tz).strftime("%H:%M"),
            a.end.astimezone(WINDOW[0].tz).strftime("%H:%M"),
        )
        for a in meter["sensor"].search_annotations()
    }


def test_findings_outside_the_window_are_left_as_they_are(meter):
    check(meter, finding("01:00", "02:00"), finding("10:00", "11:00"))

    later_window = (at("03:00"), at("12:00"))
    assert check(meter, belief_time=RUN + timedelta(hours=1), window=later_window) == 1

    assert current(meter) == [
        ("01:00", "02:00", "warning", "No data since 01:00"),
        ("10:00", "11:00", "label", "Resolved: No data since 10:00"),
    ]


def test_a_finding_that_began_before_the_window_is_compared_with_its_stored_version(
    meter,
):
    check(meter, finding("01:00", "04:00"))

    later_window = (at("03:00"), at("12:00"))
    assert (
        check(
            meter,
            finding("01:00", "04:00"),
            belief_time=RUN + timedelta(hours=1),
            window=later_window,
        )
        == 0
    )


def test_a_rerun_at_the_same_belief_time_replaces_its_version(meter, fresh_db):
    check(meter, finding("03:15", "05:45"))
    check(meter, finding("03:15", "06:00"))
    fresh_db.session.flush()

    assert len(meter["sensor"].search_annotations()) == 1
    assert current(meter) == [("03:15", "06:00", "warning", "No data since 03:15")]


def test_findings_name_their_source(meter):
    with pytest.raises(ValueError, match="name no source"):
        save_generator_results(
            [
                dict(
                    kind="annotations",
                    subject=meter["sensor"],
                    window=WINDOW,
                    annotations=[],
                )
            ]
        )


# ― Checking findings, and what a job says about them ―――――――――――――――――――――――――――――――――――――――――


def test_findings_are_judged_by_the_sensor_they_annotate(meter):
    result = dict(
        kind="annotations", subject=meter["sensor"], window=WINDOW, annotations=[]
    )

    with pytest.raises(GeneratorWritesUncheckedSensor) as refusal:
        check_generator_results([result], {meter["sensor"].id + 1}, "a gap check")
    assert refusal.value.refused_sensor_ids == [meter["sensor"].id]
    check_generator_results([result], {meter["sensor"].id}, "a gap check")


def test_a_job_counts_findings_as_annotations(meter):
    saved = save_generator_results(
        [
            dict(
                kind="annotations",
                subject=meter["sensor"],
                source=meter["source"],
                window=WINDOW,
                belief_time=RUN,
                annotations=[finding("03:15", "05:45"), finding("07:00", "08:00")],
            )
        ]
    )

    assert outputs_of_job_result(saved) == [
        {
            "sensor": meter["sensor"].id,
            "num-computed-annotations": 2,
            "num-recorded-annotations": 2,
        }
    ]


# ― A reporter that annotates ――――――――――――――――――――――――――――――――――――――――――――――――――――――――――――


class FindingsParametersSchema(ReporterParametersSchema):
    output = fields.List(fields.Nested(Output()), load_default=list)


class FindingsReporter(Reporter):
    """Report the same findings on each of its input sensors."""

    __version__ = "1"
    __author__ = "test"
    _parameters_schema = FindingsParametersSchema()

    FINDINGS: list[dict] = []

    @property
    def annotated_sensors(self) -> list:
        return self.input_sensors

    def _compute_report(self, **kwargs) -> list[dict]:
        return [
            dict(
                kind="annotations",
                subject=item["sensor"],
                window=(kwargs["start"], kwargs["end"]),
                annotations=self.FINDINGS,
            )
            for item in kwargs["input"]
        ]


def test_a_reporter_that_annotates(meter, fresh_db):
    FindingsReporter.FINDINGS = [finding("03:15", "05:45")]
    reporter = FindingsReporter()
    parameters = dict(
        input=[dict(sensor=meter["sensor"].id)],
        start=WINDOW[0].isoformat(),
        end=WINDOW[1].isoformat(),
    )

    # Annotating a sensor is checked as recording on it
    sensors = resolve_data_generator_sensors(
        reporter, reporter._parameters_schema.load(parameters)
    )
    assert sensors["output_sensors"] == [meter["sensor"]]

    results = reporter.compute(parameters=parameters)
    assert results[0]["source"] == reporter.data_source
    save_generator_results(results)
    fresh_db.session.commit()

    [annotation] = fresh_db.session.scalars(select(Annotation)).all()
    assert annotation.source == reporter.data_source
    assert annotation.type == "warning"
    assert annotation.belief_time is not None


def test_a_report_that_finds_nothing_is_no_warning(app, caplog):
    """For a check, finding nothing is the good outcome, not a sign of misaligned inputs."""
    from flexmeasures.data.services.reporting import log_report_outcome

    results = [dict(kind="annotations", annotations=[])]
    saved = [dict(sensor_id=3, kind="annotations", n_computed=0, n_rows=0)]

    with caplog.at_level("INFO"):
        log_report_outcome("a gap check", results, saved)

    assert [record.levelname for record in caplog.records] == ["INFO"]
    assert "sensor 3: 0 finding(s), 0 version(s) recorded" in caplog.text
