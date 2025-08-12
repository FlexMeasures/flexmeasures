import functools

import click
import marshmallow as ma
from webargs.flaskparser import parser, use_kwargs
from webargs.multidictproxy import MultiDictProxy
from werkzeug.datastructures import MultiDict
from click import get_current_context
from flask import Request
from flask.cli import with_appcontext as with_cli_appcontext
from pint import DefinitionSyntaxError, DimensionalityError, UndefinedUnitError

from flexmeasures.utils.unit_utils import to_preferred, ur


class MarshmallowClickMixin(click.ParamType):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = self.__class__.__name__

    def get_metavar(self, param, **kwargs):
        return self.__class__.__name__

    def convert(self, value, param, ctx, **kwargs):
        try:
            return self.deserialize(value, **kwargs)
        except ma.exceptions.ValidationError as e:
            raise click.exceptions.BadParameter(e, ctx=ctx, param=param)


class FMValidationError(ma.exceptions.ValidationError):
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


def convert_to_quantity(value: str, to_unit: str) -> ur.Quantity:
    """Convert value to quantity in the given unit.

    :param value:       Value to convert.
    :param to_unit:     Unit to convert to. If the unit starts with a '/',
                        the value can have any unit, and the unit is used as the denominator.
    :returns:           Quantity in the desired unit.
    """
    if to_unit.startswith("/") and len(to_unit) < 2:
        raise ValueError(f"Variable `to_unit='{to_unit}'` must define a denominator.")
    try:
        if to_unit.startswith("/"):
            return to_preferred(
                ur.Quantity(value) * ur.Quantity(to_unit[1:])
            ) / ur.Quantity(to_unit[1:])
        return ur.Quantity(value).to(ur.Quantity(to_unit))
    except DimensionalityError as e:
        raise FMValidationError(f"Cannot convert value `{value}` to '{to_unit}'") from e
    except (AssertionError, DefinitionSyntaxError, UndefinedUnitError) as e:
        raise FMValidationError(
            f"Cannot convert value '{value}' to a valid quantity. {e}"
        )


@parser.location_loader("path_and_files")
def load_data_from_path_and_files(request: Request, schema):
    """
    Custom webargs location loader to extract data from both path parameters and uploaded files.

    This loader combines variables from the request URL path (`request.view_args`) and
    uploaded file data (`request.files`) into a single MultiDict, which is then passed to
    webargs for validation and deserialization.

    Note:
        If any keys are present in both `request.view_args` and `request.files`,
        the file data will overwrite the path data for those keys.

    Parameters:
        request (Request): The incoming Flask request object.
        schema: The webargs schema used to validate and deserialize the extracted data.

    Returns:
        MultiDictProxy: A proxy object wrapping the merged data from path parameters
                        and uploaded files.
    """
    data = MultiDict(request.view_args)
    data.update(request.files)
    belief_time = request.form.get("belief-time-measured-instantly")
    data.update({"belief-time-measured-instantly": belief_time})
    return MultiDictProxy(data, schema)


query = functools.partial(use_kwargs, location="query")
body = functools.partial(use_kwargs, location="json")
path_and_files = functools.partial(use_kwargs, location="path_and_files")
