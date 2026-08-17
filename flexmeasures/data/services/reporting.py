"""Logic for queueing and running reporting jobs."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from flask import current_app
from rq.job import Job

from flexmeasures.data import db
from flexmeasures.data.utils import save_to_db

if TYPE_CHECKING:
    from flexmeasures.data.models.reporting import Reporter


def create_reporting_job(reporter: "Reporter", queue: str = "reporting") -> Job:
    """Queue a job that computes a report and stores its results."""
    reporter._data_source = db.session.merge(reporter.data_source)
    db.session.flush()
    data_source_id = reporter._data_source.id
    db.session.commit()

    parameters = reporter._parameters_schema.dump(reporter._parameters)
    output_sensor_ids = [output["sensor"] for output in parameters["output"]]
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
        timeout=60 * 60,
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
    for result in results:
        save_to_db(result["data"])
    db.session.commit()
    return [
        {"sensor_id": result["sensor"].id, "n_rows": len(result["data"])}
        for result in results
    ]
