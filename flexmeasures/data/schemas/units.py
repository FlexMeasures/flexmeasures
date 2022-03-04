from typing import Optional

from marshmallow import fields, validate, ValidationError
from marshmallow.validate import Validator

from flexmeasures.data.schemas.utils import MarshmallowClickMixin
from flexmeasures.utils.unit_utils import is_valid_unit, ur


class NonNegativeFloat(fields.Float, MarshmallowClickMixin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Insert validation into self.validators so that multiple errors can be stored.
        validator = validate.Range(min=0)
        self.validators.insert(0, validator)


class Quantity(Validator):
    """Validator which succeeds if the value passed to it is a valid quantity."""

    def __init__(self, *, error: Optional[str] = None):
        self.error = error

    def __call__(self, value):
        if not is_valid_unit(value):
            raise ValidationError("Not a valid quantity")
        return value


class QuantityField(fields.Str, MarshmallowClickMixin):
    """Marshmallow/Click field for validating quantities against a unit registry.

    The FlexMeasures unit registry is based on the pint library.

    For example:
        >>> percentage_field = QuantityField("%", validate=validate.Range(min=0, max=1))
        >>> percentage_field.deserialize("2.5%")
        2.5
        >>> percentage_field.deserialize(0.025)
        2.5
        >>> power_field = QuantityField("kW", validate=validate.Range(max=ur.Quantity("1 kW")))
        >>> power_field.deserialize("120 W")
        0.12
    """

    def __init__(self, to_unit: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Insert validation into self.validators so that multiple errors can be stored.
        validator = Quantity()
        self.validators.insert(0, validator)
        self.to_unit = ur.Quantity(to_unit)

    def _deserialize(self, value, attr, obj, **kwargs) -> ur.Quantity:
        """Turn a quantity describing string into a float magnitude."""
        return ur.Quantity(value).to(self.to_unit).magnitude

    def _serialize(self, value, attr, data, **kwargs):
        """Turn a Quantity into a string in scientific format."""
        return "{:~P}".format(value.to(self.to_unit))
