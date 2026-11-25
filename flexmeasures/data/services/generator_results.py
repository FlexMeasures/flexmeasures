"""Checking and saving what a data generator returns, in one way for every kind of data generator.

A data generator, such as a scheduler, a reporter, a forecaster or a plugin's automation type,
returns its results as dicts naming the "sensor" to record on and holding the "data" to record there.
Whichever kind of generator it is, and whether it runs in a worker or from the CLI,
its results are checked against the sensors it may record on and saved the same way here.

A data generator can also return findings about a sensor, such as gaps in its data, rather than data to record.
Such a result is of the kind "annotations": it names its "subject" (the sensor the findings are about),
the "window" it checked, as a (start, end) pair, and holds the "annotations" it found there,
each a dict with a start, an end, a type and a content, and optionally a belief time.
For example:

    {
        "kind": "annotations",
        "subject": <Sensor 3>,
        "window": (start, end),
        "annotations": [{"start": ..., "end": ..., "type": "warning", "content": "No data for meter 3 since 2026-11-12 03:15 CET"}],
        "belief_time": ...,  # optional, by default the moment it is saved
    }

The generator decides everything about a finding, including its type, which says how urgent it is.
The findings are saved as versions of annotations, as beliefs are (see `save_annotation_result`).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING

from flexmeasures.data import db
from flexmeasures.data.utils import save_to_db_and_count
from flexmeasures.utils.time_utils import server_now

if TYPE_CHECKING:
    from flexmeasures.data.models.annotations import Annotation
    from flexmeasures.data.models.data_sources import DataSource
    from flexmeasures.data.models.time_series import Sensor

#: The kind of result that holds findings about a sensor, to be saved as annotations on it.
ANNOTATIONS = "annotations"


def is_annotation_result(result: dict) -> bool:
    """Tell whether a result holds findings to save as annotations, rather than beliefs."""
    return result.get("kind") == ANNOTATIONS


def result_content(result: dict):
    """Return what a result holds: the beliefs to record, or the findings to save as annotations."""
    return result["annotations"] if is_annotation_result(result) else result["data"]


def describe_annotation_result(result: dict) -> str:
    """Describe the findings of a result of annotations, one per line, as a dry run shows them instead of saving them."""
    subject = result["subject"]
    window_start, window_end = result["window"]
    findings = result["annotations"]
    lines = [
        f"{len(findings)} finding(s) on sensor {subject.id} ({subject.name}), from {window_start} to {window_end}:"
    ]
    lines += [
        f"- {finding['type']} from {finding['start']} to {finding['end']}: {finding['content']}"
        for finding in findings
    ]
    return "\n".join(lines)


def result_sensor(result: dict) -> "Sensor | None":
    """Return the sensor a result records on: the sensor of its beliefs, or the subject of its annotations."""
    return (
        result.get("subject") if is_annotation_result(result) else result.get("sensor")
    )


class GeneratorWritesUncheckedSensor(Exception):
    """Raised when a data generator returns results for a sensor that nobody's permissions were checked against.

    It is a refusal rather than a passing failure: the same results are refused again on every retry,
    until the generator's configuration or the sensors it was checked against change.
    It derives from Exception rather than PermissionError,
    because PermissionError is the operating system's (an OSError), which the same jobs raise when they cannot write a file.
    The facts are kept as attributes, so that a handler need not read them from the message.
    """

    def __init__(
        self,
        generator: str,
        refused_sensor_ids: Iterable[int],
        permitted_sensor_ids: Iterable[int],
        automation_id: int | None = None,
    ):
        self.generator = generator
        self.refused_sensor_ids = sorted(set(refused_sensor_ids))
        self.permitted_sensor_ids = sorted(set(permitted_sensor_ids))
        self.automation_id = automation_id
        checked_against = (
            f"automation {automation_id} was checked against when it was created"
            if automation_id is not None
            else "it may record on"
        )
        super().__init__(
            f"{generator} would record data on sensor(s) {', '.join(str(i) for i in self.refused_sensor_ids)},"
            f" which are not among the sensors {checked_against}"
            f" ({', '.join(str(i) for i in self.permitted_sensor_ids) or 'none'})."
        )

    def __reduce__(self):
        """Rebuild the refusal from its fields, so that it survives pickling, as an RQ job's meta pickles it.

        Exception rebuilds an instance from its args, which hold only the message,
        and this constructor needs the fields, so without this an unpickled job meta would lose every key it holds.
        """
        return (
            type(self),
            (
                self.generator,
                self.refused_sensor_ids,
                self.permitted_sensor_ids,
                self.automation_id,
            ),
        )


def describe_generator(generator) -> str:
    """Name a data generator for a message: its class, and its data source if it already has one.

    The data source is only named when the generator already holds it, since asking for it could create one.
    """
    source = getattr(generator, "_data_source", None)
    if source is not None and source.id is not None:
        return f"{type(generator).__name__} (data source {source.id})"
    return type(generator).__name__


def check_generator_results(
    results: list[dict],
    permitted_sensor_ids: set[int] | None,
    generator: str,
    automation_id: int | None = None,
) -> None:
    """Refuse results for any sensor outside the permitted ones, judging the whole set before any of it is saved or handed back.

    A result of annotations is judged by its subject, the sensor it annotates.
    A result without a sensor, such as a scheduler's own bookkeeping, records on no sensor, so it is not judged.
    Pass None for permitted_sensor_ids where no such check applies, as on the CLI, whose user is trusted.

    :raises GeneratorWritesUncheckedSensor: naming the generator, the refused sensors and the permitted ones.
    """
    if permitted_sensor_ids is None:
        return
    sensors = [result_sensor(result) for result in results]
    refused = {
        sensor.id
        for sensor in sensors
        if sensor is not None and sensor.id not in permitted_sensor_ids
    }
    if refused:
        raise GeneratorWritesUncheckedSensor(
            generator, refused, permitted_sensor_ids, automation_id
        )


def check_results_of_current_job(results: list[dict], generator) -> None:
    """Refuse results for any sensor outside those the automation behind the current job was checked against.

    Outside a job, or in a job that no automation queued, nothing is checked, as for every caller of ``check_generator_results``.

    :raises GeneratorWritesUncheckedSensor: naming the generator, the automation, the refused sensors and the permitted ones.
    """
    from rq import get_current_job

    from flexmeasures.data.services.automations import (
        automation_id_of_job,
        sensors_automation_job_may_record_on,
    )

    rq_job = get_current_job()
    check_generator_results(
        results,
        sensors_automation_job_may_record_on(rq_job),
        describe_generator(generator),
        automation_id_of_job(rq_job),
    )


def save_generator_results(results: list[dict]) -> list[dict]:
    """Save what a data generator returns, all of it or none of it, and say how many beliefs each result saved.

    The results are saved within a savepoint, so a save that fails halfway leaves none of them staged,
    while whatever the caller staged before stays as it was.
    Committing is left to the caller, as it is for ``save_to_db``, so that the results can be part of a larger transaction.
    Every result saved must name its sensor, unlike for the check:
    a result without one, such as a scheduler's own bookkeeping, holds no beliefs, so the caller leaves it out, as ``make_schedule`` does.
    A belief that repeats the belief right before it is not saved again, as for any other data,
    which also makes saving results a generator already saved itself cost nothing extra.
    A result may name events whose beliefs are saved even so, under "save_even_if_unchanged" (their event starts),
    as a report does where its belief has to supersede a belief of another source recorded since (see `AggregatorReporter`).

    A result of annotations is saved by `save_annotation_result`, and counts annotations rather than beliefs, under "kind": "annotations".

    :returns: per result, the sensor id, the number of beliefs computed ("n_computed") and the number of beliefs saved ("n_rows").
        The computed count is every belief the generator returned, including NaN values and beliefs that were already on record.
        The saved count leaves both of those out, so a rerun that only repeats what is on record saves 0 of the beliefs it computed.
    """
    saved = []
    with db.session.begin_nested():
        for result in results:
            if is_annotation_result(result):
                saved.append(
                    {
                        "sensor_id": result["subject"].id,
                        "kind": ANNOTATIONS,
                        "n_computed": len(result["annotations"]),
                        "n_rows": save_annotation_result(result),
                    }
                )
                continue
            data = result["data"]
            forced = result.get("save_even_if_unchanged")
            if forced is None or len(forced) == 0:
                _, n_saved = save_to_db_and_count(data)
            else:
                is_forced = data.index.get_level_values("event_start").isin(forced)
                _, n_changed = save_to_db_and_count(data[~is_forced])
                _, n_forced = save_to_db_and_count(
                    data[is_forced], save_changed_beliefs_only=False
                )
                n_saved = n_changed + n_forced
            saved.append(
                {
                    "sensor_id": result["sensor"].id,
                    "n_computed": len(data),
                    "n_rows": n_saved,
                }
            )
    return saved


def save_results_not_yet_saved(results: list[dict]) -> None:
    """Save the results that do not say how many of their beliefs were saved, and record that number on each of them as "n_saved".

    A generator that saves its results as it goes, such as the built-in forecasting pipeline, says so with "n_saved" on each result,
    and is not saved again.
    One that only returns its results has them saved here,
    and one that saved them itself anyway costs nothing extra, since its beliefs are then already on record.
    Committing is left to the caller.
    """
    unsaved = [result for result in results if "n_saved" not in result]
    if not unsaved:
        return
    for result, saved in zip(unsaved, save_generator_results(unsaved)):
        result["n_saved"] = saved["n_rows"]


def outputs_of_job_result(saved: list[dict]) -> list[dict]:
    """Turn what ``save_generator_results`` says about each result into the "outputs" a job result reports, as API clients read them.

    Each output names its sensor (by ID), the number of beliefs computed ("num-computed-beliefs") and the number of beliefs recorded ("num-recorded-beliefs"),
    counted as ``save_generator_results`` counts them.
    For a result of annotations, they count annotations instead ("num-computed-annotations" and "num-recorded-annotations").
    """
    outputs = []
    for entry in saved:
        what = "annotations" if entry.get("kind") == ANNOTATIONS else "beliefs"
        outputs.append(
            {
                "sensor": entry["sensor_id"],
                f"num-computed-{what}": entry["n_computed"],
                f"num-recorded-{what}": entry["n_rows"],
            }
        )
    return outputs


def save_annotation_result(result: dict) -> int:
    """Save the findings of a result of annotations as new versions of the annotations on its subject, and return how many versions were saved.

    A finding is identified by its subject, its source and its start, as is the annotation it is saved as.
    Each run saves a new version of a finding with the run's belief time, so that the most recent version is the current one,
    as `search_annotations` shows with ``most_recent_beliefs_only``.
    A version is never changed afterwards, so the history of a finding stays on record.

    The result holds every finding for its subject over the checked window, so the findings are reconciled with what is stored,
    that is, with the most recent versions from the same source on the same subject, as known at the run's belief time:

    - a finding that is new, or that differs from its most recent version in its end, type or content, is saved as a new version;
    - a finding that is the same as its most recent version is not saved again, just as an unchanged belief is not;
    - a stored finding that reaches into the window, but that the result no longer holds, gets a resolved version:
      the same start and end, the type "label" and a content saying it was resolved.
      A finding that is already resolved stays as it is.

    Stored findings that lie wholly before or after the window are left as they are, as the result does not judge them.
    A version that would have the same belief time as the most recent version replaces it, as a run cannot hold two beliefs at the same moment.
    Committing is left to the caller.

    :param result: a result of the kind "annotations", which also names its "source",
                   as `DataGenerator.compute` assigns it.
    :returns: the number of versions saved, including resolved versions.
    """
    from flexmeasures.data.models.annotations import Annotation
    from flexmeasures.data.queries.annotations import query_sensor_annotations

    subject: Sensor = result["subject"]
    source: DataSource | None = result.get("source")
    if source is None:
        raise ValueError(
            f"The annotations for sensor {subject.id} name no source, which their data generator assigns when it computes them."
        )
    window_start, window_end = result["window"]
    belief_time: datetime = result.get("belief_time") or server_now()
    findings = result["annotations"]

    # The most recent versions to compare with: those reaching into the window, and those of the findings, which may start before it.
    earliest = min([window_start] + [finding["start"] for finding in findings])
    stored = db.session.scalars(
        query_sensor_annotations(
            subject.id,
            annotations_after=earliest,
            annotations_before=window_end,
            beliefs_before=belief_time,
            sources=[source],
            most_recent_beliefs_only=True,
        )
    ).all()
    latest_by_start: dict[datetime, Annotation] = {
        annotation.start: annotation for annotation in stored
    }

    n_saved = 0
    for finding in findings:
        latest = latest_by_start.get(finding["start"])
        if latest is not None and (latest.end, latest.type, latest.content) == (
            finding["end"],
            finding["type"],
            finding["content"],
        ):
            continue
        _save_version(
            subject,
            source,
            latest,
            start=finding["start"],
            end=finding["end"],
            annotation_type=finding["type"],
            content=finding["content"],
            belief_time=finding.get("belief_time") or belief_time,
        )
        n_saved += 1

    found_starts = {finding["start"] for finding in findings}
    for latest in stored:
        if (
            latest.start in found_starts
            or latest.type == "label"
            or latest.end <= window_start
        ):
            continue
        _save_version(
            subject,
            source,
            latest,
            start=latest.start,
            end=latest.end,
            annotation_type="label",
            content=resolved_content(latest.content),
            belief_time=belief_time,
        )
        n_saved += 1
    return n_saved


def resolved_content(content: str) -> str:
    """Say that a finding was resolved, in the content of its resolved version."""
    return f"Resolved: {content}"


def _save_version(
    subject: "Sensor",
    source: "DataSource",
    latest: "Annotation | None",
    start: datetime,
    end: datetime,
    annotation_type: str,
    content: str,
    belief_time: datetime,
) -> None:
    """Stage a new version of an annotation on a sensor, or update its most recent version if that has the same belief time."""
    from flexmeasures.data.models.annotations import Annotation

    if latest is not None and latest.belief_time == belief_time:
        latest.end = end
        latest.type = annotation_type
        latest.content = content
        return
    subject.annotations.append(
        Annotation(
            start=start,
            end=end,
            type=annotation_type,
            content=content,
            belief_time=belief_time,
            source=source,
        )
    )
