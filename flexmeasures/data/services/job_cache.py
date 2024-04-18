"""
Logic around storing and retrieving jobs from redis cache.
"""

from __future__ import annotations

import redis

from redis.exceptions import ConnectionError
from rq.job import Job, NoSuchJobError


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

    def _get_job(self, job_id: str) -> Job:
        try:
            job = Job.fetch(job_id, connection=self.connection)
        except NoSuchJobError:
            return None
        return job

    def get(
        self, asset_or_sensor_id: int, queue: str, asset_or_sensor_type: str
    ) -> list[Job]:
        self._check_redis_connection()

        job_ids_to_remove, jobs = list(), list()
        cache_key = self._get_cache_key(asset_or_sensor_id, queue, asset_or_sensor_type)
        for job_id in self.connection.smembers(cache_key):
            job_id = job_id.decode("utf-8")
            job = self._get_job(job_id)
            # remove job from cache if cant be found - was removed by TTL
            if job is None:
                job_ids_to_remove.append(job_id)
                continue
            jobs.append(job)
        if job_ids_to_remove:
            self.connection.srem(cache_key, *job_ids_to_remove)
        return jobs
