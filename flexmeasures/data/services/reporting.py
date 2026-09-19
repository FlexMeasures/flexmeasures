"""Logic for queueing and running reporting jobs."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from flask import current_app
from rq import get_current_job
from rq.job import Job

from flexmeasures.data import db
from flexmeasures.data.schemas.reporting import ReporterParametersSchema
from flexmeasures.data.utils import save_to_db

if TYPE_CHECKING:
    from flexmeasures.data.models.reporting import Reporter


def create_reporting_job(reporter: "Reporter", queue: str = "reporting") -> Job:
    """Queue a job that computes a report and stores its results."""
    parameters = reporter._parameters_schema.dump(reporter._parameters)
    ReporterParametersSchema(only=("input", "output")).load(
        {
            field: parameters[field]
            for field in ("input", "output")
            if field in parameters
        }
    )
    output_sensor_ids = [output["sensor"] for output in parameters["output"]]

    # The reporting worker runs in a separate process, so the data source has to be committed before the job is enqueued.
    # Note that reporter.data_source may have only just created it, and that our views do not auto-commit.
    reporter._data_source = db.session.merge(reporter.data_source)
    db.session.commit()
    data_source_id = reporter._data_source.id

    job_metadata = {
        "data_source_info": {"id": data_source_id},
        "start": parameters.get("start"),
        "end": parameters.get("end"),
        "sensor_id": output_sensor_ids[0],
    }
    if reporter._job_trigger:
        job_metadata["trigger"] = reporter._job_trigger

    job = Job.create(
        run_report_job,
        kwargs={"data_source_id": data_source_id, "parameters": parameters},
        connection=current_app.queues[queue].connection,
        ttl=int(
            current_app.config.get(
                "FLEXMEASURES_JOB_TTL", timedelta(-1)
            ).total_seconds()
        ),
        result_ttl=int(
            current_app.config.get(
                "FLEXMEASURES_PLANNING_TTL", timedelta(-1)
            ).total_seconds()
        ),
        meta=job_metadata,
    )
    current_app.queues[queue].enqueue_job(job)
    for sensor_id in output_sensor_ids:
        current_app.job_cache.add(
            sensor_id,
            job_id=job.id,
            queue=queue,
            asset_or_sensor_type="sensor",
        )
    return job


def _count_persistable_values(data) -> int:
    """Count computed values that will not be dropped as NaN before persistence.

    This does not account for valid values that ``save_to_db`` may skip because
    they are unchanged.
    """
    from timely_beliefs import BeliefsSeries

    if isinstance(data, BeliefsSeries):
        return int(data.notna().sum())
    return len(data.dropna(subset=["event_value"]))


class ReportWritesUncheckedSensor(PermissionError):
    """Raised when a reporter returns results for a sensor that nobody's permissions were checked against."""


def compute_and_save_report(
    reporter: "Reporter",
    parameters: dict,
    persist: bool = True,
    permitted_output_sensor_ids: set[int] | None = None,
    automation_id: int | None = None,
) -> tuple[list[dict], list[dict]]:
    """Compute a report and, unless told otherwise, persist its results.

    This is the single place where report computation and persistence meet, shared by
    the synchronous CLI and the background worker. With persist=False (dry runs),
    results are computed but nothing is written.

    :param reporter: the reporter computing the report.
    :param parameters: the reporter parameters to compute with.
    :param persist: whether to persist the computed results. Pass False for dry runs.
    :param permitted_output_sensor_ids: if given, every computed result must record
        on one of these sensors, or a ReportWritesUncheckedSensor error is raised
        before anything is written. Pass None where no such guard applies (e.g. the CLI).
    :param automation_id: named in the ReportWritesUncheckedSensor error, if raised.
    :returns: the computed results, and per result a summary of what was saved
        (the sensor id plus the number of persistable values, counted with
        _count_persistable_values semantics). With persist=False the summary is empty.
    """
    results = reporter.compute(parameters=parameters)
    saved: list[dict] = []
    if not persist:
        return results, saved
    if permitted_output_sensor_ids is not None:
        refused = sorted(
            {
                result["sensor"].id
                for result in results
                if result["sensor"].id not in permitted_output_sensor_ids
            }
        )
        if refused:
            raise ReportWritesUncheckedSensor(
                f"This report would record data on sensor(s) {', '.join(str(i) for i in refused)},"
                f" which are not among the sensors automation {automation_id}"
                " was checked against when it was created."
            )
    for result in results:
        n_rows = _count_persistable_values(result["data"])
        save_to_db(result["data"])
        saved.append({"sensor_id": result["sensor"].id, "n_rows": n_rows})
    db.session.commit()
    return results, saved


def run_report_job(data_source_id: int, parameters: dict) -> list[dict]:
    """Compute and store a report in a reporting worker.

    If the report was triggered by an automation, the end of the report window is recorded upon success,
    so the automation's next default window starts where this one ended.
    A failed report job therefore leaves no permanent gap in the reported periods.
    """
    from flexmeasures.data.models.data_sources import DataSource
    from flexmeasures.data.models.reporting import Reporter

    source = db.session.get(DataSource, data_source_id)
    if source is None:
        raise ValueError(f"Data source {data_source_id} no longer exists.")
    reporter = source.data_generator
    if not isinstance(reporter, Reporter):
        raise ValueError(f"Data source {data_source_id} does not store a Reporter.")
    reporter._parameters = None

    # An automation's job may only record on the sensors its creator was checked against.
    # Judge the whole set before writing any of it.
    from flexmeasures.data.services.automations import (
        sensors_automation_job_may_record_on,
    )

    rq_job = get_current_job()
    permitted_output_sensor_ids = sensors_automation_job_may_record_on(rq_job)
    automation_id = (
        rq_job.meta["trigger"]["automation_id"]
        if permitted_output_sensor_ids is not None
        else None
    )
    results, saved = compute_and_save_report(
        reporter,
        parameters,
        persist=True,
        permitted_output_sensor_ids=permitted_output_sensor_ids,
        automation_id=automation_id,
    )

    summary = ", ".join(
        f"{result['n_rows']} values on sensor {result['sensor_id']}" for result in saved
    )
    if any(result["n_rows"] for result in saved):
        current_app.logger.info(
            "Report by %s ran successfully, producing %s.", source, summary
        )
    else:
        current_app.logger.warning(
            "Report by %s produced no persistable values (%s). This can happen when its inputs do not align on source and belief time.",
            source,
            summary,
        )

    # The job's trigger says whether an automation created it, as it does for the guard above.
    if automation_id is not None and parameters.get("end"):
        from flexmeasures.data.services.automations import record_automation_run

        record_automation_run(
            automation_id, now=datetime.fromisoformat(parameters["end"])
        )

    return saved
