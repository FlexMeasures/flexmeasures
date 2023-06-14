""" Various coding utils (e.g. around function decoration) """
from __future__ import annotations

import functools
import time
import inspect
import importlib
import pkgutil
from flask import current_app


def make_registering_decorator(foreign_decorator):
    """
    Returns a copy of foreign_decorator, which is identical in every
    way(*), except also appends a .decorator property to the callable it
    spits out.

    # (*)We can be somewhat "hygienic", but new_decorator still isn't signature-preserving,
    i.e. you will not be able to get a runtime list of parameters. For that, you need hackish libraries...
    but in this case, the only argument is func, so it's not a big issue

    Works on outermost decorators, based on Method 3 of https://stackoverflow.com/a/5910893/13775459
    """

    def new_decorator(func):
        # Call to new_decorator(method)
        # Exactly like old decorator, but output keeps track of what decorated it
        r = foreign_decorator(
            func
        )  # apply foreign_decorator, like call to foreign_decorator(method) would have done
        r.decorator = new_decorator  # keep track of decorator
        r.original = func  # keep track of decorated function
        return r

    new_decorator.__name__ = foreign_decorator.__name__
    new_decorator.__doc__ = foreign_decorator.__doc__

    return new_decorator


def methods_with_decorator(cls, decorator):
    """
    Returns all methods in CLS with DECORATOR as the
    outermost decorator.

    DECORATOR must be a "registering decorator"; one
    can make any decorator "registering" via the
    make_registering_decorator function.

    Doesn't work for the @property decorator, but does work for the @functools.cached_property decorator.

    Works on outermost decorators, based on Method 3 of https://stackoverflow.com/a/5910893/13775459
    """
    for maybe_decorated in cls.__dict__.values():
        if hasattr(maybe_decorated, "decorator"):
            if maybe_decorated.decorator == decorator:
                if hasattr(maybe_decorated, "original"):
                    yield maybe_decorated.original
                else:
                    yield maybe_decorated


def rgetattr(obj, attr, *args):
    """Get chained properties.

    Usage
    -----
    >>> class Pet:
            def __init__(self):
                self.favorite_color = "orange"
    >>> class Person:
            def __init__(self):
                self.pet = Pet()
    >>> p = Person()
    >>> rgetattr(p, 'pet.favorite_color')  # "orange"

    From https://stackoverflow.com/a/31174427/13775459"""

    def _getattr(obj, attr):
        return getattr(obj, attr, *args)

    return functools.reduce(_getattr, [obj] + attr.split("."))


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


def flatten_unique(nested_list_of_objects: list) -> list:
    """Returns unique objects in a possibly nested (one level) list of objects.

    For example:
    >>> flatten_unique([1, [2, 3, 4], 3, 5])
    <<< [1, 2, 3, 4, 5]
    """
    all_objects = []
    for s in nested_list_of_objects:
        if isinstance(s, list):
            all_objects.extend(s)
        else:
            all_objects.append(s)
    return list(set(all_objects))


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
