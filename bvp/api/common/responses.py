from typing import List
import inflect

p = inflect.engine()


def invalid_domain() -> dict:
    return dict(
        result="Rejected",
        status="INVALID_DOMAIN",
        message="Connections should be identified using the EA1 addressing scheme recommended by USEF. "
        "For example: 'ea1.2018-06.com.bvp.api:<owner-id>:<asset-id>'",
    )


def invalid_period() -> dict:
    return dict(
        result="Rejected",
        status="INVALID_PERIOD",
        message="The time period in your request doesn't seem right. "
        "If you wish to post meter data for the future, set 'simulation' to 'true'.",
    )


def invalid_ptu_duration() -> dict:
    return dict(
        result="Rejected",
        status="INVALID_PTU_DURATION",
        message="Start time should be on the hour or a multiple of 15 minutes thereafter, "
        "duration should be some multiple N of 15 minutes, and "
        "the number of values should be some factor of N.",
    )


def invalid_role(requested_access_role: str) -> dict:
    return dict(
        result="Rejected",
        status="INVALID_ROLE",
        message="No known services for specified role %s." % requested_access_role,
    )


def invalid_sender(user_role_names: List[str], *allowed_role_names: str) -> dict:
    if not user_role_names:
        user_roles_str = "have no role"
    else:
        user_role_names = [p.a(role_name) for role_name in user_role_names]
        user_roles_str = "are %s" % p.join(user_role_names)
    allowed_role_names = [pluralize(role_name) for role_name in allowed_role_names]
    allowed_role_names = p.join(allowed_role_names)
    return dict(
        result="Rejected",
        status="INVALID_SENDER",
        message="You don't have the right role to access this service. "
        "You %s while this service is reserved for %s."
        % (user_roles_str, allowed_role_names),
    )


def invalid_timezone() -> dict:
    return dict(
        result="Rejected",
        status="INVALID_TIMEZONE",
        message="Start time should explicitly state a timezone.",
    )


def invalid_unit() -> dict:
    return dict(
        result="Rejected",
        status="INVALID_UNIT",
        message="Meter data should be given in MW.",
    )


def ptus_incomplete() -> dict:
    return dict(result="Rejected", status="PTUS_INCOMPLETE", message="Missing values.")


def unrecognized_connection_group() -> dict:
    return dict(
        result="Rejected",
        status="UNRECOGNIZED_CONNECTION_GROUP",
        message="One or more connections in your request were not found in your account.",
    )


def pluralize(usef_role_name):
    """Adding a trailing 's' works well for USEF roles."""
    return "%ss" % usef_role_name
