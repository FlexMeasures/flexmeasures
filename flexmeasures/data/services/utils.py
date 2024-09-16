from __future__ import annotations

import hashlib
import base64
from typing import Type
import functools
from copy import deepcopy
import inspect

import click
from sqlalchemy import JSON, String, cast, literal
from flask import current_app
from rq.job import Job
from sqlalchemy import select

from flexmeasures import Sensor, Asset
from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.planning import Scheduler


def get_scheduler_instance(
    scheduler_class: Type[Scheduler], asset_or_sensor: Asset | Sensor, scheduler_params
) -> Scheduler:
    """
    Get an instance of a Scheduler adapting for the previous Scheduler signature,
    where a sensor is passed, to the new one where the asset_or_sensor is introduced.
    """

    _scheduler_params = deepcopy(scheduler_params)

    if "asset_or_sensor" not in inspect.signature(scheduler_class).parameters:
        _scheduler_params["sensor"] = asset_or_sensor
    else:
        _scheduler_params["asset_or_sensor"] = asset_or_sensor

    return scheduler_class(**_scheduler_params)


def get_asset_or_sensor_ref(asset_or_sensor: Asset | Sensor) -> dict:
    return {"id": asset_or_sensor.id, "class": asset_or_sensor.__class__.__name__}


def get_asset_or_sensor_from_ref(asset_or_sensor: dict):
    """
    Fetch Asset or Sensor object described by the asset_or_sensor dictionary.
    This dictionary needs to contain the class name and row id.

    We currently cannot simplify this by just passing around the object
    instead of the class name: i.e. the function arguments need to
    be serializable as job parameters.

    Examples:

    >> get_asset_or_sensor({"class" : "Asset", "id" : 1})

    Asset(id=1)

    >> get_asset_or_sensor({"class" : "Sensor", "id" : 2})

    Sensor(id=2)
    """
    if asset_or_sensor["class"] == Asset.__name__:
        klass = Asset
    elif asset_or_sensor["class"] == Sensor.__name__:
        klass = Sensor
    else:
        raise ValueError(
            f"Unrecognized class `{asset_or_sensor['class']}`. Please, consider using GenericAsset or Sensor."
        )

    return db.session.get(klass, asset_or_sensor["id"])


def get_or_create_model(
    model_class: Type[GenericAsset | GenericAssetType | Sensor], **kwargs
) -> GenericAsset | GenericAssetType | Sensor:
    """Get a model from the database or add it if it's missing.

    For example:
    >>> weather_station_type = get_or_create_model(
    >>>     GenericAssetType,
    >>>     name="weather station",
    >>>     description="A weather station with various sensors.",
    >>> )
    """

    # unpack custom initialization parameters that map to multiple database columns
    init_kwargs = kwargs.copy()
    lookup_kwargs = kwargs.copy()
    if "knowledge_horizon" in kwargs:
        (
            lookup_kwargs["knowledge_horizon_fnc"],
            lookup_kwargs["knowledge_horizon_par"],
        ) = lookup_kwargs.pop("knowledge_horizon")

    # Find out which attributes are dictionaries mapped to JSON database columns,
    # or callables mapped to string database columns (by their name)
    filter_json_kwargs = {}
    filter_by_kwargs = lookup_kwargs.copy()
    for kw, arg in lookup_kwargs.items():
        model_attribute = getattr(model_class, kw)
        if hasattr(model_attribute, "type") and isinstance(model_attribute.type, JSON):
            filter_json_kwargs[kw] = filter_by_kwargs.pop(kw)
        elif callable(arg) and isinstance(model_attribute.type, String):
            # Callables are stored in the database by their name
            # e.g. knowledge_horizon_fnc = x_days_ago_at_y_oclock
            # is stored as "x_days_ago_at_y_oclock"
            filter_by_kwargs[kw] = filter_by_kwargs[kw].__name__
        else:
            # The kw is already present in filter_by_kwargs and doesn't need to be adapted
            # i.e. it can be used as an argument to .filter_by()
            pass

    # See if the model already exists as a db row
    model_query = select(model_class).filter_by(**filter_by_kwargs)
    for kw, arg in filter_json_kwargs.items():
        model_query = model_query.filter(
            cast(getattr(model_class, kw), String) == cast(literal(arg, JSON()), String)
        )
    model = db.session.execute(model_query).scalar_one_or_none()

    # Create the model and add it to the database if it didn't already exist
    if model is None:
        model = model_class(**init_kwargs)
        click.echo(f"Created {model}")
        db.session.add(model)
    return model


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
    :param queue: name of the queue
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Get the redis connection
            connection = current_app.redis_connection

            requeue = kwargs.pop("requeue", False)

            # checking if force is an input argument of `func`
            force_new_job_creation = kwargs.pop("force_new_job_creation", False)

            # creating a hash from args and kwargs
            args_hash = (
                f"{queue}:{func.__name__}:{hash_function_arguments(args, kwargs)}"
            )

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
            connection.set(
                args_hash, job.id, ex=current_app.config["FLEXMEASURES_JOB_CACHE_TTL"]
            )

            return job

        return wrapper

    return decorator
