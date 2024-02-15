from __future__ import annotations

from typing import Type


class MissingAttributeException(Exception):
    pass


class WrongTypeAttributeException(Exception):
    pass


def check_required_attributes(
    sensor: "Sensor",  # noqa: F821
    attributes: list[str | tuple[str, Type | tuple[Type, ...]]],
):
    """Raises if any attribute in the list of attributes is missing on the Sensor, or has the wrong type.

    :param sensor: Sensor object to check for attributes
    :param attributes: List of either an attribute name or a tuple of an attribute name and its allowed type
                       (the allowed type may also be a tuple of several allowed types)
    """
    missing_attributes: list[str] = []
    wrong_type_attributes: list[tuple[str, Type, Type]] = []
    for attribute_field in attributes:
        if isinstance(attribute_field, str):
            attribute_name = attribute_field
            expected_attribute_type = None
        elif isinstance(attribute_field, tuple) and len(attribute_field) == 2:
            attribute_name = attribute_field[0]
            expected_attribute_type = attribute_field[1]
        else:
            raise ValueError("Unexpected declaration of attributes")

        # Check attribute exists
        if not sensor.has_attribute(attribute_name):
            missing_attributes.append(attribute_name)

        # Check attribute is of the expected type
        if expected_attribute_type is not None:
            attribute = sensor.get_attribute(attribute_name)
            if not isinstance(attribute, expected_attribute_type):
                wrong_type_attributes.append(
                    (attribute_name, type(attribute), expected_attribute_type)
                )
    if missing_attributes:
        raise MissingAttributeException(
            f"Sensor is missing required attributes: {', '.join(missing_attributes)}"
        )
    if wrong_type_attributes:
        error_message = ""
        for (
            attribute_name,
            attribute_type,
            expected_attribute_type,
        ) in wrong_type_attributes:
            error_message += f"- attribute '{attribute_name}' is a {attribute_type} instead of a {expected_attribute_type}\n"
        raise WrongTypeAttributeException(
            f"Sensor attributes are not of the required type:\n {error_message}"
        )
