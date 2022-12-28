import functools

import click
import marshmallow as ma
from click import get_current_context
from flask import Request
from flask.cli import with_appcontext as with_cli_appcontext
from marshmallow import ValidationError
from webargs.flaskparser import parser, use_kwargs
from webargs.multidictproxy import MultiDictProxy


class MarshmallowClickMixin(click.ParamType):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = self.__class__.__name__

    def get_metavar(self, param):
        return self.__class__.__name__

    def convert(self, value, param, ctx, **kwargs):
        try:
            return self.deserialize(value, **kwargs)
        except ma.exceptions.ValidationError as e:
            raise click.exceptions.BadParameter(e, ctx=ctx, param=param)


class FMValidationError(ValidationError):
    """
    Custom validation error class.
    It differs from the classic validation error by having two
    attributes, according to the USEF 2015 reference implementation.
    Subclasses of this error might adjust the `status` attribute accordingly.
    """

    result = "Rejected"
    status = "UNPROCESSABLE_ENTITY"


def with_appcontext_if_needed():
    """Execute within the script's application context, in case there is one.

    An exception is `flexmeasures run`, which has a click context at the time the decorator is called,
    but no longer has a click context at the time the decorated function is called,
    which, typically, is a request to the running FlexMeasures server.
    """

    def decorator(f):
        ctx = get_current_context(silent=True)
        if ctx and not ctx.invoked_subcommand == "run":
            return with_cli_appcontext(f)
        return f

    return decorator


@parser.location_loader("path_and_files")
def load_data_from_path_and_files(request: Request, schema):
    # Load data from two locations: path (request.view_args) and files
    data = request.view_args.copy()  # path variables
    data.update(request.files)
    return MultiDictProxy(data, schema)


query = functools.partial(use_kwargs, location="query")
body = functools.partial(use_kwargs, location="json")
path_and_files = functools.partial(use_kwargs, location="path_and_files")
