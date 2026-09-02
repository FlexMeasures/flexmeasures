"""Logic for queueing and running reporting jobs."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from flask import current_app
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
    db.session.flush()
    data_source_id = reporter._data_source.id
    db.session.commit()

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


def run_report_job(data_source_id: int, parameters: dict) -> list[dict]:
    """Compute and store a report in a reporting worker."""
    from flexmeasures.data.models.data_sources import DataSource
    from flexmeasures.data.models.reporting import Reporter

    source = db.session.get(DataSource, data_source_id)
    if source is None:
        raise ValueError(f"Data source {data_source_id} no longer exists.")
    reporter = source.data_generator
    if not isinstance(reporter, Reporter):
        raise ValueError(f"Data source {data_source_id} does not store a Reporter.")
    reporter._parameters = None
    results = reporter.compute(parameters=parameters)
    saved = []
    for result in results:
        n_rows = _count_persistable_values(result["data"])
        save_to_db(result["data"])
        saved.append({"sensor_id": result["sensor"].id, "n_rows": n_rows})
    db.session.commit()

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
    return saved
