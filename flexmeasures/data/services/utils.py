from __future__ import annotations

from typing import Type

import click
from sqlalchemy import JSON, String, cast, literal

from flexmeasures import Sensor
from flexmeasures.data import db
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType


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
    model_query = model_class.query.filter_by(**filter_by_kwargs)
    for kw, arg in filter_json_kwargs.items():
        model_query = model_query.filter(
            cast(getattr(model_class, kw), String) == cast(literal(arg, JSON()), String)
        )
    model = model_query.one_or_none()

    # Create the model and add it to the database if it didn't already exist
    if model is None:
        model = model_class(**init_kwargs)
        click.echo(f"Created {model}")
        db.session.add(model)
    return model
