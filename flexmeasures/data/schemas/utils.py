import click
import marshmallow as ma
from click import get_current_context
from flask.cli import with_appcontext as with_cli_appcontext
from pint import DefinitionSyntaxError, DimensionalityError, UndefinedUnitError

from flexmeasures.utils.unit_utils import to_preferred, ur


def _format_validation_error(error: ma.exceptions.ValidationError) -> str:
    """Flatten a marshmallow validation error into a single human-readable line."""
    messages = error.messages
    if isinstance(messages, dict):
        return "; ".join(
            f"{field}: {' '.join(str(m) for m in msgs) if isinstance(msgs, list) else msgs}"
            for field, msgs in messages.items()
        )
    if isinstance(messages, list):
        return " ".join(str(message) for message in messages)
    return str(messages)


class MarshmallowClickMixin:
    def __init__(self, *args, **kwargs):

        metadata_keys = ["description", "example"]
        metadata = dict(kwargs.get("metadata", {}))
        for key in metadata_keys:
            value = kwargs.pop(key, None)
            if value is not None:
                metadata[key] = value
        if metadata:
            kwargs["metadata"] = metadata

        super().__init__(*args, **kwargs)
        self.name = self.__class__.__name__
        self.__name__ = self.name

    def get_metavar(self, param, **kwargs):
        return self.__class__.__name__

    def convert(self, value, param, ctx, **kwargs):
        try:
            return self.deserialize(value, **kwargs)
        except ma.exceptions.ValidationError as e:
            raise click.exceptions.BadParameter(e, ctx=ctx, param=param)

    def __call__(self, value):
        """Support click.FuncParamType by behaving like a conversion callable.

        We raise a click error rather than a ValueError, because click.FuncParamType
        turns a ValueError into a message that shows only the offending value
        (`self.fail(value, ...)`), which would swallow the validation message
        (e.g. "No account found with id 9999.").
        """
        try:
            return self.deserialize(value)
        except ma.exceptions.ValidationError as e:
            raise click.exceptions.BadParameter(_format_validation_error(e)) from e


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

    An exception is any server ``run`` command (e.g. ``flexmeasures run`` or ``flask run``),
    which has a click context at the time the decorator is called,
    but no longer has a click context at the time the decorated function is called,
    which, typically, is a request to the running FlexMeasures server.

    The check walks up the entire context chain so it handles both:
    - ``flask run``: modules are imported while the ``run`` subcommand context is *current*
      (``ctx.info_name == "run"``, ``ctx.invoked_subcommand is None``).
    - ``flexmeasures run``: modules are imported at group level, where the parent context
      has ``invoked_subcommand == "run"``.
    """

    def decorator(f):
        ctx = get_current_context(silent=True)
        # Walk up the context chain: if any level is a "run" command we are serving HTTP
        # requests and must NOT wrap with the CLI app-context decorator.
        check = ctx
        while check is not None:
            if check.info_name == "run" or check.invoked_subcommand == "run":
                return f
            check = check.parent
        if ctx is not None:
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


def snake_to_kebab(key: str) -> str:
    """Convert snake_case to kebab-case."""
    return key.replace("_", "-")


def kebab_to_snake(key: str) -> str:
    """Convert kebab-case to snake_case."""
    return key.replace("-", "_")


class SupportsLegacyFieldAliases:
    """Mixin that lets a request schema accept legacy field names as aliases for their canonical replacements.

    Subclasses set `legacy_field_aliases`, a dict mapping a legacy incoming
    key (as sent by an older client) to the schema's current, canonical
    `data_key`. This lets us rename a public request field without breaking
    clients that still send the old name: both are accepted, and only the
    canonical field ends up being deserialized.

    This is for request fields only. Response fields can't "accept either"
    key on the way out, so backward compatibility there means including both
    keys in the response body instead (see e.g. `job`/`schedule` in the
    scheduling trigger response).
    """

    legacy_field_aliases: dict[str, str] = {}

    @ma.pre_load
    def _apply_legacy_field_aliases(self, data, **kwargs):
        if not hasattr(data, "items") or not self.legacy_field_aliases:
            return data
        # Only rebuild `data` into a plain dict if a legacy key is actually
        # present. Some incoming `data` objects are a MultiDict (e.g. when
        # webargs represents a JSON list as repeated keys) and other pre_load
        # hooks may rely on that (e.g. `getlist`); leave those untouched when
        # there's nothing for us to alias.
        if not any(legacy_key in data for legacy_key in self.legacy_field_aliases):
            return data
        aliased = dict(data)
        for legacy_key, canonical_key in self.legacy_field_aliases.items():
            if legacy_key in aliased and canonical_key not in aliased:
                aliased[canonical_key] = aliased.pop(legacy_key)
        return aliased
