"""
Logic around storing and retrieving jobs from redis cache.
"""

from __future__ import annotations

from itertools import chain
from typing import Iterable

import redis

from redis.exceptions import ConnectionError
from rq.job import Job


class NoRedisConfigured(Exception):
    def __init__(self, message="Redis not configured"):
        super().__init__(message)


class JobCache:
    """
    Class is used for storing jobs and retrieving them from redis cache.
    Need it to be able to get jobs for particular asset (and display them on status page).
    Keeps cache up to date by removing jobs that are not found in redis - were removed by TTL.
    Stores jobs by asset or sensor id, queue and asset or sensor type, cache key can look like this
        - forecasting:sensor:1 (forecasting jobs can be stored by sensor only)
        - scheduling:sensor:2
        - scheduling:asset:3
    """

    def __init__(self, connection: redis.Redis):
        self.connection = connection

    def _get_cache_key(
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
        cache_key = self._get_cache_key(asset_or_sensor_id, queue, asset_or_sensor_type)
        self.connection.sadd(cache_key, job_id)

    def get(
        self, asset_or_sensor_id: int, queue: str, asset_or_sensor_type: str
    ) -> list[Job]:
        """Fetch the jobs listed under one asset or sensor."""
        entry = (asset_or_sensor_id, queue, asset_or_sensor_type)
        return self.get_many([entry])[entry]

    def get_many(
        self, entries: Iterable[tuple[int, str, str]]
    ) -> dict[tuple[int, str, str], list[Job]]:
        """Fetch the jobs listed under several assets or sensors, in a fixed number of Redis round trips.

        Each entry is a tuple of asset or sensor id, queue and asset or sensor type, as passed to get().
        However many entries and jobs there are, this pings Redis once, reads all job IDs in one pipeline and all jobs in another,
        so that a page listing many sensors' jobs does not pay a round trip per sensor and two per job.
        Job IDs whose job can no longer be found (it was removed by TTL) are removed from their entry.
        """
        entries = list(dict.fromkeys(entries))
        self._check_redis_connection()
        cache_keys = [self._get_cache_key(*entry) for entry in entries]

        with self.connection.pipeline(transaction=False) as pipeline:
            for cache_key in cache_keys:
                pipeline.smembers(cache_key)
            job_ids_per_entry = [
                [job_id.decode("utf-8") for job_id in job_ids]
                for job_ids in pipeline.execute()
            ]

        # A job can be listed under several entries, so it is fetched once.
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
        for entry, cache_key, job_ids in zip(entries, cache_keys, job_ids_per_entry):
            jobs[entry] = [
                jobs_by_id[job_id]
                for job_id in job_ids
                if jobs_by_id[job_id] is not None
            ]
            expired = [job_id for job_id in job_ids if jobs_by_id[job_id] is None]
            if expired:
                expired_job_ids[cache_key] = expired
        if expired_job_ids:
            with self.connection.pipeline(transaction=False) as pipeline:
                for cache_key, job_ids in expired_job_ids.items():
                    pipeline.srem(cache_key, *job_ids)
                pipeline.execute()
        return jobs
