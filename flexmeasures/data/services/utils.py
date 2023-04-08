import functools
from flask import current_app
from rq.job import Job

import hashlib
import base64


def make_hash_sha256(o):
    """
    SHA256 instead of Python's hash function because apparently, python native hashing function
    yields different results on restarts.
    Source: https://stackoverflow.com/a/42151923
    """
    hasher = hashlib.sha256()
    hasher.update(repr(make_hashable(o)).encode())
    return base64.b64encode(hasher.digest()).decode()


def make_hashable(o):
    """
    Function to create hashes for dictionaries with nested objects
    Source: https://stackoverflow.com/a/42151923
    """
    if isinstance(o, (tuple, list)):
        return tuple((make_hashable(e) for e in o))

    if isinstance(o, dict):
        return tuple(sorted((k, make_hashable(v)) for k, v in o.items()))

    if isinstance(o, (set, frozenset)):
        return tuple(sorted(make_hashable(e) for e in o))

    if callable(
        getattr(o, "make_hashable", None)
    ):  # checks if the object o has the method make_hashable
        return o.make_hashable()

    return o


def hash_function_arguments(args, kwags):
    """Combines the hashes of the args and kargs

    The way to go to do h(x,y) = hash(hash(x) || hash(y)) because it avoid the following:

    1) h(x,y) = hash(x || y), might create a collision if we delete the last n characters of x and we append them in front of y. e.g h("abc", "d") = h("ab", "cd")
    2) we don't want to sort x and y, because we need the function h(x,y) != h(y,x)
    3) extra hashing just avoid that we can't decompose the input arguments and track if the same args or kwarg are called several times. More of a security measure I think.

    source: https://crypto.stackexchange.com/questions/55162/best-way-to-hash-two-values-into-one
    """
    return make_hash_sha256(
        make_hash_sha256(args) + make_hash_sha256(kwags)
    )  # concat two hashes


def job_cache(queue: str):
    """
    To avoid recomputing the same task multiple times, this decorator checks if the function has already been called with the
    same arguments. Input arguments are hashed and stored as Redis keys with the values being the job IDs `input_arguments_hash:job_id`).

    The benefits of using redis to store the input arguments over a local cache, such as LRU Cache, are:
    1) It will work in distributed environments (in computing clusters), where multiple workers will avoid repeating
      work as the cache will be shared across them.
    2) Cached calls are logged, which means that we can easily debug.
    3) Cache will still be there on restarts.

    Arguments
    :param queue: name of the queue (just used to find the redis connection)
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Get the redis connection for the given queue
            connection = current_app.queues[queue].connection

            requeue = kwargs.pop("requeue", False)

            # checking if force is an input argument of `func`
            force_new_job_creation = kwargs.pop("force_new_job_creation", False)

            # creating a hash from args and kwargs
            args_hash = hash_function_arguments(args, kwargs)

            # check the redis connection for whether the key hash exists
            if connection.exists(args_hash) and not force_new_job_creation:
                current_app.logger.info(
                    f"The function {func.__name__} has been called already with the same arguments. Skipping..."
                )

                # get job id
                job_id = connection.get(args_hash).decode()

                # check if the job exists and, if it doesn't, skip fetching and generate new job
                if Job.exists(job_id, connection=connection):
                    job = Job.fetch(
                        job_id, connection=connection
                    )  # get job object from job id

                    # requeue if failed and requeue flag is true
                    if job.is_failed and requeue:
                        job.requeue()

                    return job  # returning the same job regardless of the status (SUCCESS, FAILED, ...)

            # if the job description is new -> create job
            job = func(*args, **kwargs)  # create a new job

            # store function call in redis by mapping the hash of the function arguments to its job id
            connection.set(args_hash, job.id)

            return job

        return wrapper

    return decorator
