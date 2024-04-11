"""
Logic around storing and retrieving jobs from redis cache.
"""

from rq.job import Job, NoSuchJobError


class JobCache:
    def __init__(self, connection):
        self.connection = connection

    def _get_cache_key(self, asset_or_sensor_id, queue, asset_or_sensor_type):
        return f"{queue}:{asset_or_sensor_type}:{asset_or_sensor_id}"

    def add(self, asset_or_sensor_id, job_id, queue, asset_or_sensor_type):
        cache_key = self._get_cache_key(asset_or_sensor_id, queue, asset_or_sensor_type)
        self.connection.sadd(cache_key, job_id)

    def _get_job(self, job_id):
        try:
            job = Job.fetch(job_id, connection=self.connection)
        except NoSuchJobError:
            return None
        return job

    def get(self, asset_or_sensor_id, queue, asset_or_sensor_type):
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
