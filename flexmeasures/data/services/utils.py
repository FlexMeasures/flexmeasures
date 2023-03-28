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


def redis_cache(queue):
    """
    Decorator that checks if a function has already been called with the same arguments and
    fetches the job using the job id, which is stored in Redis.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Creating a hash from args and kwargs
            args_hash = hash_function_arguments(args, kwargs)

            # check if the key hash exists in the redis queue
            if current_app.queues[queue].connection.exists(args_hash):
                current_app.logger.info(
                    f"The function {func.__name__} has been called alread with the same arguments. Skipping..."
                )

                # get job id
                job_id = current_app.queues[queue].connection.get(args_hash).decode()

                # get job object from job id
                return Job.fetch(
                    job_id, connection=current_app.queues[queue].connection
                )
            else:  # new call

                # call function
                job = func(*args, **kwargs)

                # store function call in redis
                current_app.queues[queue].connection.set(
                    args_hash, job.id
                )  # setting return value of function call to the hash of its inputs

                return job  # todo: try catch, if it fails, don't hash it or impose a max retry number

        return wrapper

    return decorator
