"""
Index RQ jobs by asset or sensor, and look them up again.
"""

from __future__ import annotations

from datetime import datetime

import redis

from redis.exceptions import ConnectionError
from rq.job import Job
from rq.utils import str_to_date


class NoRedisConfigured(Exception):
    def __init__(self, message="Redis not configured"):
        super().__init__(message)


class JobMap:
    """
    Map assets or sensors and queues to RQ job IDs in Redis.

    Job creation code adds IDs to Redis sets. Listing code uses those IDs to
    retrieve jobs from RQ, which stores the job records separately. An expired
    job's ID remains in the map until a read removes it.

    Each index key contains the queue, entity type, and entity ID:
        - forecasting:sensor:1 (forecasting jobs can be stored by sensor only)
        - scheduling:sensor:2
        - scheduling:asset:3

    get() fetches all matching jobs. get_enqueued_at() reads only the fields
    needed to check that each job exists and sort it by enqueue time. This lets
    a paginated listing fetch full records only for the requested page with
    fetch_jobs().
    """

    def __init__(self, connection: redis.Redis):
        self.connection = connection

    def _redis_index_key(
        self, asset_or_sensor_id: int, queue: str, asset_or_sensor_type: str
    ) -> str:
        return f"{queue}:{asset_or_sensor_type}:{asset_or_sensor_id}"

    def _check_redis_connection(self):
        try:
            self.connection.ping()  # Check if the Redis connection is okay
        except (ConnectionError, ConnectionRefusedError):
            raise NoRedisConfigured

    def add(
        self,
        asset_or_sensor_id: int,
        job_id: str,
        queue: str = None,
        asset_or_sensor_type: str = None,
    ):
        self._check_redis_connection()
        index_key = self._redis_index_key(
            asset_or_sensor_id, queue, asset_or_sensor_type
        )
        self.connection.sadd(index_key, job_id)

    def _get_job_ids(self, index_key: str) -> list[str]:
        return [
            job_id.decode("utf-8") for job_id in self.connection.smembers(index_key)
        ]

    def get(
        self, asset_or_sensor_id: int, queue: str, asset_or_sensor_type: str
    ) -> list[Job]:
        """Fetch the current jobs from the Redis ID index."""
        self._check_redis_connection()
        index_key = self._redis_index_key(
            asset_or_sensor_id, queue, asset_or_sensor_type
        )
        job_ids_to_remove, jobs = list(), list()
        job_ids = self._get_job_ids(index_key)
        for job_id, job in zip(
            job_ids, Job.fetch_many(job_ids, connection=self.connection)
        ):
            # Remove the ID from the Redis index when its RQ job has expired.
            if job is None:
                job_ids_to_remove.append(job_id)
                continue
            jobs.append(job)
        if job_ids_to_remove:
            self.connection.srem(index_key, *job_ids_to_remove)
        return jobs

    def get_enqueued_at(
        self, asset_or_sensor_id: int, queue: str, asset_or_sensor_type: str
    ) -> list[tuple[str, datetime | None]]:
        """List the current job IDs from the Redis ID index, each with the time its job was enqueued.

        Only these fields are read, rather than the full jobs, so that all jobs can be sorted cheaply.
        A job that was created but not enqueued yet (e.g. one waiting on another job) comes with None.
        """
        self._check_redis_connection()
        index_key = self._redis_index_key(
            asset_or_sensor_id, queue, asset_or_sensor_type
        )
        job_ids = self._get_job_ids(index_key)
        pipeline = self.connection.pipeline()
        for job_id in job_ids:
            pipeline.hmget(Job.key_for(job_id), "created_at", "enqueued_at")
        job_ids_to_remove, enqueued_ats = list(), list()
        for job_id, (created_at, enqueued_at) in zip(job_ids, pipeline.execute()):
            # Every RQ job records when it was created, so both fields missing means the job has expired.
            if created_at is None and enqueued_at is None:
                job_ids_to_remove.append(job_id)
                continue
            enqueued_ats.append(
                (job_id, str_to_date(enqueued_at) if enqueued_at else None)
            )
        if job_ids_to_remove:
            self.connection.srem(index_key, *job_ids_to_remove)
        return enqueued_ats

    def fetch_jobs(self, job_ids: list[str]) -> list[Job | None]:
        """Fetch the given jobs, in order, with None for each job that has expired meanwhile."""
        self._check_redis_connection()
        return Job.fetch_many(job_ids, connection=self.connection)
