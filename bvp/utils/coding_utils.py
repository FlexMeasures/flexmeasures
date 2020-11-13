import functools


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


def sort_dict(unsorted_dict: dict) -> dict:
    sorted_dict = dict(sorted(unsorted_dict.items(), key=lambda item: item[0]))
    return sorted_dict
