"""
Logic around storing and retrieving jobs from redis cache.
"""

from __future__ import annotations

from collections import OrderedDict
from time import monotonic

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
    Redis sets index job IDs by asset or sensor and queue; RQ stores the job records separately.
    get() reads the current jobs from Redis and removes IDs whose jobs expired.
    get_for_status_page() keeps fetched job lists in process for one minute, so
    paging does not fetch the same jobs repeatedly.
    The Redis index key includes asset or sensor ID, queue, and entity type:
        - forecasting:sensor:1 (forecasting jobs can be stored by sensor only)
        - scheduling:sensor:2
        - scheduling:asset:3
    """

    STATUS_SNAPSHOT_TTL_SECONDS = 60
    STATUS_SNAPSHOT_MAX_ENTRIES = 2048

    def __init__(self, connection: redis.Redis):
        self.connection = connection
        self._status_page_job_lists: OrderedDict[str, tuple[float, list[Job]]] = (
            OrderedDict()
        )

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
        # The Redis index changed, so this worker's fetched list is stale.
        self._status_page_job_lists.pop(index_key, None)

    def get(
        self, asset_or_sensor_id: int, queue: str, asset_or_sensor_type: str
    ) -> list[Job]:
        """Fetch current jobs from the Redis ID index."""
        return self._get_jobs(asset_or_sensor_id, queue, asset_or_sensor_type, False)

    def get_for_status_page(
        self, asset_or_sensor_id: int, queue: str, asset_or_sensor_type: str
    ) -> list[Job]:
        """Reuse a short-lived in-process list for status-page paging."""
        return self._get_jobs(asset_or_sensor_id, queue, asset_or_sensor_type, True)

    def _get_jobs(
        self,
        asset_or_sensor_id: int,
        queue: str,
        asset_or_sensor_type: str,
        use_status_snapshot: bool,
    ) -> list[Job]:
        index_key = self._redis_index_key(
            asset_or_sensor_id, queue, asset_or_sensor_type
        )
        if use_status_snapshot:
            cached = self._status_page_job_lists.get(index_key)
            if cached is not None and cached[0] > monotonic():
                # Keep recently used entries when the cache reaches its size limit.
                self._status_page_job_lists.move_to_end(index_key)
                return cached[1]

        self._check_redis_connection()

        job_ids_to_remove, jobs = list(), list()
        job_ids = [
            job_id.decode("utf-8") for job_id in self.connection.smembers(index_key)
        ]
        for job_id, job in zip(
            job_ids, Job.fetch_many(job_ids, connection=self.connection)
        ):
            # remove job from cache if cant be found - was removed by TTL
            if job is None:
                job_ids_to_remove.append(job_id)
                continue
            jobs.append(job)
        if job_ids_to_remove:
            self.connection.srem(index_key, *job_ids_to_remove)
        if use_status_snapshot:
            self._status_page_job_lists[index_key] = (
                monotonic() + self.STATUS_SNAPSHOT_TTL_SECONDS,
                jobs,
            )
            self._status_page_job_lists.move_to_end(index_key)
            if len(self._status_page_job_lists) > self.STATUS_SNAPSHOT_MAX_ENTRIES:
                self._status_page_job_lists.popitem(last=False)
        return jobs
