"""
Logic for queueing and running reporting jobs.
"""

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
    """Queue a job that computes a report and saves the results to the database.

    The reporter's (loaded) parameters are re-serialized into the job,
    and the reporter itself travels as its data source ID (which stores its config),
    so the job is fully deserializable by the worker.
    """
    # Ensure the data source ID is available in the database when the job runs.
    reporter._data_source = db.session.merge(reporter.data_source)
    db.session.flush()
    data_source_id = reporter._data_source.id
    db.session.commit()

    parameters = reporter._parameters_schema.dump(reporter._parameters)
    output_sensor_ids = [
        output["sensor"] for output in parameters.get("output", []) or []
    ]

    # job metadata for tracking (datetimes as ISO strings,
    # a workaround for https://github.com/Parallels/rq-dashboard/issues/510)
    job_metadata = {
        "data_source_info": {"id": data_source_id},
        "start": parameters.get("start"),
        "end": parameters.get("end"),
        "sensor_id": output_sensor_ids[0] if output_sensor_ids else None,
    }
    if reporter._job_trigger:
        job_metadata["trigger"] = reporter._job_trigger

    job = Job.create(
        run_report_job,
        kwargs=dict(
            data_source_id=data_source_id,
            parameters=parameters,
            automation_id=(reporter._job_trigger or {}).get("automation_id"),
        ),
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
        ),  # NB job.cleanup docs says a negative number of seconds means persisting forever
        meta=job_metadata,
        timeout=60 * 60,  # 1 hour
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


def run_report_job(
    data_source_id: int, parameters: dict, automation_id: int | None = None
) -> list[dict]:
    """Compute a report (with the data generator stored on the given data source)
    and save the results to the database.

    This function is meant to be run by a worker processing the reporting queue.
    If the report was triggered by an automation, the end of the report window is
    recorded upon success, so the automation's next default window starts there.
    """
    from flexmeasures.data.models.data_sources import DataSource
    from flexmeasures.data.models.reporting import Reporter

    source = db.session.get(DataSource, data_source_id)
    if source is None:
        raise ValueError(f"Data source {data_source_id} no longer exists.")
    reporter = source.data_generator
    if not isinstance(reporter, Reporter):
        raise ValueError(f"Data source {data_source_id} does not store a Reporter.")
    # The data generator instance is cached on the data source, which may be shared
    # (e.g. within a long-lived worker process), so wipe any previous parameter state.
    reporter._parameters = None
    results = reporter.compute(parameters=parameters)
    for result in results:
        save_to_db(result["data"])
    db.session.commit()

    if automation_id is not None and parameters.get("end"):
        from datetime import datetime

        from flexmeasures.data.services.automations import record_automation_run

        record_automation_run(
            automation_id, now=datetime.fromisoformat(parameters["end"])
        )

    # return a light summary (the report data itself is stored in the database)
    return [
        {"sensor_id": result["sensor"].id, "n_rows": len(result["data"])}
        for result in results
    ]
