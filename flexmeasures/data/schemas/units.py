from __future__ import annotations

from marshmallow import fields, validate, ValidationError
from pint import DefinitionSyntaxError, DimensionalityError, UndefinedUnitError

from flexmeasures.data.schemas.utils import FMValidationError, MarshmallowClickMixin
from flexmeasures.utils.unit_utils import (
    is_valid_unit,
    to_preferred,
    ur,
)


class QuantityValidator(validate.Validator):
    """Validator which succeeds if the value passed to it is a valid quantity."""

    def __init__(self, *, error: str | None = None):
        self.error = error

    def __call__(self, value):
        if not is_valid_unit(value):
            raise ValidationError("Not a valid quantity")
        return value


class QuantityField(MarshmallowClickMixin, fields.Str):
    """Marshmallow/Click field for validating quantities against a unit registry.

    The FlexMeasures unit registry is based on the pint library.

    For example:
        >>> percentage_field = QuantityField("%", validate=validate.Range(min=0, max=1))
        >>> percentage_field.deserialize("2.5%")
        <Quantity(2.5, 'percent')>
        >>> percentage_field.deserialize(0.025)
        <Quantity(2.5, 'percent')>
        >>> power_field = QuantityField("kW", validate=validate.Range(max=ur.Quantity("1 kW")))
        >>> power_field.deserialize("120 W")
        <Quantity(0.12, 'kilowatt')>
    """

    def __init__(
        self,
        to_unit: str,
        *args,
        default_src_unit: str | None = None,
        return_magnitude: bool = False,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        # Insert validation into self.validators so that multiple errors can be stored.
        validator = QuantityValidator()
        self.validators.insert(0, validator)
        if to_unit.startswith("/"):
            if len(to_unit) < 2:
                raise ValueError(
                    f"Variable `to_unit='{to_unit}'` must define a denominator."
                )
            self.to_unit = ur.Quantity(to_unit[1:])
            self.any_unit = True
        else:
            self.to_unit = ur.Quantity(to_unit)
            self.any_unit = False
        self.default_src_unit = default_src_unit
        self.return_magnitude = return_magnitude

    def _deserialize(
        self,
        value,
        attr,
        obj,
        return_magnitude: bool | None = None,
        **kwargs,
    ) -> ur.Quantity:
        """Turn a quantity describing string into a Quantity."""
        if return_magnitude is None:
            return_magnitude = self.return_magnitude
        if isinstance(value, str):
            if not is_valid_unit(value):
                raise ValidationError("Not a valid quantity")
            try:
                if self.any_unit:
                    q = to_preferred(ur.Quantity(value) * self.to_unit) / self.to_unit
                else:
                    q = ur.Quantity(value).to(self.to_unit)
            except DimensionalityError as e:
                raise FMValidationError(
                    f"Cannot convert value `{value}` to '{self.to_unit}'"
                ) from e
            except (AssertionError, DefinitionSyntaxError, UndefinedUnitError) as e:
                raise FMValidationError(
                    f"Cannot convert value `{value}` to a valid quantity. {e}"
                )
        elif self.default_src_unit is not None:
            q = self._deserialize(
                f"{value} {self.default_src_unit}",
                attr,
                obj,
                **kwargs,
                return_magnitude=False,
            )
        else:
            q = self._deserialize(
                f"{value}", attr, obj, **kwargs, return_magnitude=False
            )
        if return_magnitude:
            return q.magnitude
        return q

    def _serialize(self, value, attr, data, **kwargs):
        """Turn a Quantity into a string in scientific format."""
        return "{:~P}".format(value.to(self.to_unit))
