from __future__ import annotations

from typing import Type

from flexmeasures.auth.policy import (
    ADMIN_ROLE,
    ACCOUNT_ADMIN_ROLE,
    CONSULTANT_ROLE,
    ADMIN_READER_ROLE,
)

# from flexmeasures.data.models.user import User, Role


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


def can_modify_role(current_user: "User", roles_to_modify: list["Role"]):  # noqa: F821
    """Check if the current user can modify the role.

    :param current_user: The current user.
    :param role_to_modify: The role to modify.
    :return: True if the user can modify the role, False otherwise.

    The roles are:
    - admin: can only be changed in CLI / directly in the DB
    - admin-reader: can be added and removed by admins
    - account-admin: can be added and removed by admins and consultants
    - consultant: can be added and removed by admins and account-admins

    """
    for role in roles_to_modify:
        if not role:
            raise ValueError("A role in the list does not exist or is invalid (None).")
        if role.name == ADMIN_ROLE:
            raise ValueError(
                "You cannot modify the admin role. Please do this in the CLI or directly in the DB."
            )
        if role.name == ADMIN_READER_ROLE and current_user.has_role(ADMIN_ROLE):
            return True
        if role.name == ACCOUNT_ADMIN_ROLE and (
            current_user.has_role(ADMIN_ROLE) or current_user.has_role(CONSULTANT_ROLE)
        ):
            return True
        if role.name == CONSULTANT_ROLE and (
            current_user.has_role(ADMIN_ROLE)
            or current_user.has_role(ACCOUNT_ADMIN_ROLE)
        ):
            return True
    return False
