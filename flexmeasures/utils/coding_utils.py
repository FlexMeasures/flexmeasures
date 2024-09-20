""" Various coding utils (e.g. around function decoration) """
from __future__ import annotations

import functools
import time
import inspect
import importlib
import pkgutil
from flask import current_app


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
