"""
Index RQ jobs by asset or sensor, and look them up again.
"""

from __future__ import annotations

from datetime import datetime
from itertools import chain
from typing import Iterable

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
        entry = (asset_or_sensor_id, queue, asset_or_sensor_type)
        return self.get_many([entry])[entry]

    def get_many(
        self, entries: Iterable[tuple[int, str, str]]
    ) -> dict[tuple[int, str, str], list[Job]]:
        """Fetch the jobs indexed under several assets or sensors, in a fixed number of Redis round trips.

        Each entry is an asset or sensor id, a queue and an asset or sensor type, as passed to get().
        However many entries and jobs there are, this pings Redis once, reads every index in one pipeline
        and every job in another, so that a page listing the jobs of many sensors does not pay a round trip per sensor.
        A job indexed under several entries is fetched once.
        An ID whose job can no longer be found, because its RQ job expired, is removed from its index.
        """
        entries = list(dict.fromkeys(entries))
        self._check_redis_connection()
        index_keys = [self._redis_index_key(*entry) for entry in entries]

        with self.connection.pipeline(transaction=False) as pipeline:
            for index_key in index_keys:
                pipeline.smembers(index_key)
            job_ids_per_entry = [
                [job_id.decode("utf-8") for job_id in job_ids]
                for job_ids in pipeline.execute()
            ]

        unique_job_ids = list(dict.fromkeys(chain.from_iterable(job_ids_per_entry)))
        jobs_by_id = (
            dict(
                zip(
                    unique_job_ids,
                    Job.fetch_many(unique_job_ids, connection=self.connection),
                )
            )
            if unique_job_ids
            else {}
        )

        jobs: dict[tuple[int, str, str], list[Job]] = {}
        expired_job_ids: dict[str, list[str]] = {}
        for entry, index_key, job_ids in zip(entries, index_keys, job_ids_per_entry):
            jobs[entry] = [
                jobs_by_id[job_id]
                for job_id in job_ids
                if jobs_by_id[job_id] is not None
            ]
            expired = [job_id for job_id in job_ids if jobs_by_id[job_id] is None]
            if expired:
                expired_job_ids[index_key] = expired
        if expired_job_ids:
            with self.connection.pipeline(transaction=False) as pipeline:
                for index_key, job_ids in expired_job_ids.items():
                    pipeline.srem(index_key, *job_ids)
                pipeline.execute()
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
