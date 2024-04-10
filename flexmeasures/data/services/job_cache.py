"""
Logic around storing and retrieving jobs from redis cache.
"""


class JobCache:
    def __init__(self, connection, queues):
        self.connection = connection
        self.queues = queues

    def add(self, sensor_id, job_id):
        self.connection.sadd(sensor_id, job_id)

    def _get_job(self, job_id):
        for queue in self.queues.values():
            job = queue.fetch_job(job_id)
            if job is not None:
                return job

    def get(self, sensor_id):
        job_ids_to_remove = list()
        jobs = list()
        for job_id in self.connection.smembers(sensor_id):
            job_id = job_id.decode("utf-8")
            job = self._get_job(job_id)
            # remove job from cache if cant be found in any queue - was removed by TTL
            if job is None:
                job_ids_to_remove.append(job_id)
                continue
            jobs.append(job)
        if job_ids_to_remove:
            self.connection.srem(sensor_id, *job_ids_to_remove)
        return jobs
