""" Various coding utils (e.g. around function decoration) """

from __future__ import annotations

import functools
import time
import inspect
import importlib
import pkgutil

from sqlalchemy import select
from flask import current_app
from flask_security import current_user

from flexmeasures.data import db


def delete_key_recursive(value, key):
    """Delete key in a multilevel dictionary"""
    if isinstance(value, dict):

        if key in value:
            del value[key]

        for k, v in value.items():
            value[k] = delete_key_recursive(v, key)

        # value.pop(key, None)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            value[i] = delete_key_recursive(v, key)

    return value


def optional_arg_decorator(fn):
    """
    A decorator which _optionally_ accepts arguments.

    So a decorator like this:

    @optional_arg_decorator
    def register_something(fn, optional_arg = 'Default Value'):
        ...
        return fn

    will work in both of these usage scenarios:

    @register_something('Custom Name')
    def custom_name():
        pass

    @register_something
    def default_name():
        pass

    Thanks to https://stackoverflow.com/questions/3888158/making-decorators-with-optional-arguments#comment65959042_24617244
    """

    def wrapped_decorator(*args):
        if len(args) == 1 and callable(args[0]):
            return fn(args[0])
        else:

            def real_decorator(decoratee):
                return fn(decoratee, *args)

            return real_decorator

    return wrapped_decorator


def sort_dict(unsorted_dict: dict) -> dict:
    sorted_dict = dict(sorted(unsorted_dict.items(), key=lambda item: item[0]))
    return sorted_dict


# This function is used for sensors_to_show in follow-up PR it will be moved and renamed to flatten_sensors_to_show
def flatten_unique(nested_list_of_objects: list) -> list:
    """
    Get unique sensor IDs from a list of `sensors_to_show`.

    Handles:
    - Lists of sensor IDs
    - Dictionaries with a `sensors` key
    - Nested lists (one level)

    Example:
        Input:
        [1, [2, 20, 6], 10, [6, 2], {"title":None,"sensors": [10, 15]}, 15]

        Output:
        [1, 2, 20, 6, 10, 15]
    """
    all_objects = []
    for s in nested_list_of_objects:
        if isinstance(s, list):
            all_objects.extend(s)
        elif isinstance(s, dict):
            all_objects.extend(s["sensors"])
        else:
            all_objects.append(s)
    return list(dict.fromkeys(all_objects).keys())


def timeit(func):
    """Decorator for printing the time it took to execute the decorated function."""

    @functools.wraps(func)
    def new_func(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        elapsed_time = time.time() - start_time
        print(f"{func.__name__} finished in {int(elapsed_time * 1_000)} ms")
        return result

    return new_func


def deprecated(alternative, version: str | None = None):
    """Decorator for printing a warning error.
    alternative: importable object to use as an alternative to the function/method decorated
    version: version in which the function will be sunset
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_app.logger.warning(
                f"The method or function {func.__name__} is deprecated and it is expected to be sunset in version {version}. Please, switch to using {inspect.getmodule(alternative).__name__}:{alternative.__name__} to suppress this warning."
            )

            return func(*args, **kwargs)

        return wrapper

    return decorator


def find_classes_module(module, superclass):
    classes = []

    module_object = importlib.import_module(f"{module}")
    module_classes = inspect.getmembers(module_object, inspect.isclass)

    classes.extend(
        [
            (class_name, klass)
            for class_name, klass in module_classes
            if issubclass(klass, superclass) and klass != superclass
        ]
    )

    return classes


def find_classes_modules(module, superclass, skiptest=True):
    classes = []

    base_module = importlib.import_module(module)

    # root (__init__.py) of the base module
    classes += find_classes_module(module, superclass)

    for submodule in pkgutil.iter_modules(base_module.__path__):

        if skiptest and ("test" in f"{module}.{submodule.name}"):
            continue

        if submodule.ispkg:
            classes.extend(
                find_classes_modules(
                    f"{module}.{submodule.name}", superclass, skiptest=skiptest
                )
            )
        else:
            classes += find_classes_module(f"{module}.{submodule.name}", superclass)

    return classes


def get_classes_module(module, superclass, skiptest=True) -> dict:
    return dict(find_classes_modules(module, superclass, skiptest=skiptest))


def process_sensors(asset) -> list[dict[str, "Sensor"]]:  # noqa F821
    """
    Sensors to show, as defined by the sensors_to_show attribute.

    Sensors to show are defined as a list of sensor IDs, which are set by the "sensors_to_show" field in the asset's "attributes" column.
    Valid sensors either belong to the asset itself, to other assets in the same account, or to public assets.
    In play mode, sensors from different accounts can be added.

    Sensor IDs can be nested to denote that sensors should be 'shown together', for example, layered rather than vertically concatenated.
    Additionally, each row of sensors can be accompanied by a title.
    If no title is provided, `"title": None` will be assigned in the returned dictionary.

    How to interpret 'shown together' is technically left up to the function returning chart specifications, as are any restrictions regarding which sensors can be shown together, such as:
    - Whether they should share the same unit
    - Whether they should share the same name
    - Whether they should belong to different assets

    For example, this input denotes showing sensors 42 and 44 together:

        sensors_to_show = [40, 35, 41, [42, 44], 43, 45]

    And this input denotes showing sensors 42 and 44 together with a custom title:

        sensors_to_show = [
            {"title": "Title 1", "sensor": 40},
            {"title": "Title 2", "sensors": [41, 42]},
            [43, 44], 45, 46
        ]

    In both cases, the returned format will contain sensor objects mapped to their respective sensor IDs, as follows:

        [
            {"title": "Title 1", "sensor": <Sensor object for sensor 40>},
            {"title": "Title 2", "sensors": [<Sensor object for sensor 41>, <Sensor object for sensor 42>]},
            {"title": None, "sensors": [<Sensor object for sensor 43>, <Sensor object for sensor 44>]},
            {"title": None, "sensor": <Sensor object for sensor 45>},
            {"title": None, "sensor": <Sensor object for sensor 46>}
        ]

    In case the `sensors_to_show` field is missing, it defaults to two of the asset's sensors. These will be shown together (e.g., sharing the same y-axis) if they share the same unit; otherwise, they will be shown separately.

    Sensors are validated to ensure they are accessible by the user. If certain sensors are inaccessible, they will be excluded from the result, and a warning will be logged. The function only returns sensors that the user has permission to view.
    """
    old_sensors_to_show = (
        asset.sensors_to_show
    )  # Used to check if sensors_to_show was updated
    asset.sensors_to_show = asset.attributes.get("sensors_to_show", [])
    if not asset.sensors_to_show or asset.sensors_to_show == {}:
        sensors_to_show = asset.sensors[:2]
        if (
            len(sensors_to_show) == 2
            and sensors_to_show[0].unit == sensors_to_show[1].unit
        ):
            # Sensors are shown together (e.g. they can share the same y-axis)
            return [{"title": None, "sensors": sensors_to_show}]
        # Otherwise, show separately
        return [{"title": None, "sensors": [sensor]} for sensor in sensors_to_show]

    sensor_ids_to_show = asset.sensors_to_show
    # Import the schema for validation
    from flexmeasures.data.schemas.generic_assets import SensorsToShowSchema

    sensors_to_show_schema = SensorsToShowSchema()

    # Deserialize the sensor_ids_to_show using SensorsToShowSchema
    standardized_sensors_to_show = sensors_to_show_schema.deserialize(
        sensor_ids_to_show
    )

    sensor_id_allowlist = SensorsToShowSchema.flatten(standardized_sensors_to_show)

    # Only allow showing sensors from assets owned by the user's organization,
    # except in play mode, where any sensor may be shown
    accounts = [asset.owner] if asset.owner is not None else None
    if current_app.config.get("FLEXMEASURES_MODE") == "play":
        from flexmeasures.data.models.user import Account

        accounts = db.session.scalars(select(Account)).all()

    from flexmeasures.data.services.sensors import get_sensors

    accessible_sensor_map = {
        sensor.id: sensor
        for sensor in get_sensors(
            account=accounts,
            include_public_assets=True,
            sensor_id_allowlist=sensor_id_allowlist,
        )
    }

    # Build list of sensor objects that are accessible
    sensors_to_show = []
    missed_sensor_ids = []

    for entry in standardized_sensors_to_show:

        title = entry.get("title")
        sensors = entry.get("sensors")

        accessible_sensors = [
            accessible_sensor_map.get(sid)
            for sid in sensors
            if sid in accessible_sensor_map
        ]
        inaccessible = [sid for sid in sensors if sid not in accessible_sensor_map]
        missed_sensor_ids.extend(inaccessible)
        if accessible_sensors:
            sensors_to_show.append({"title": title, "sensors": accessible_sensors})

    if missed_sensor_ids:
        current_app.logger.warning(
            f"Cannot include sensor(s) {missed_sensor_ids} in sensors_to_show on asset {asset.id}, as it is not accessible to user {current_user}."
        )
    # check if sensors_to_show was updated
    if old_sensors_to_show != asset.sensors_to_show:
        asset.attributes["sensors_to_show"] = standardized_sensors_to_show
    db.session.commit()

    return sensors_to_show
