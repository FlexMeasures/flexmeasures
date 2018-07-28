from typing import List, Tuple, Union
import inflect

p = inflect.engine()


def invalid_domain() -> Tuple[dict, int]:
    return (
        dict(
            result="Rejected",
            status="INVALID_DOMAIN",
            message="Connections and sensors should be identified using the EA1 addressing scheme recommended by USEF. "
            "For example:"
            " 'ea1.2018-06.com.a1-bvp:<owner-id>:<asset-id>'"
            " 'ea1.2018-06.com.a1-bvp:temperature:<latitude>:<longitude>'",
        ),
        400,
    )


def invalid_horizon() -> Tuple[dict, int]:
    return (
        dict(
            result="Rejected",
            status="INVALID_HORIZON",
            message="The prognosis horizon in your request could not be parased",
        ),
        400,
    )


def invalid_period() -> Tuple[dict, int]:
    return (
        dict(
            result="Rejected",
            status="INVALID_PERIOD",
            message="The time period in your request doesn't seem right. "
            "If you wish to post meter data for the future, set 'simulation' to 'true'.",
        ),
        400,
    )


def invalid_ptu_duration() -> Tuple[dict, int]:
    return (
        dict(
            result="Rejected",
            status="INVALID_PTU_DURATION",
            message="Start time should be on the hour or a multiple of 15 minutes thereafter, "
            "duration should be some multiple N of 15 minutes, and "
            "the number of values should be some factor of N.",
        ),
        400,
    )


def invalid_resolution() -> Tuple[dict, int]:
    return (
        dict(
            result="Rejected",
            status="INVALID_RESOLUTION",
            message="Only a 15 minute resolution is currently supported.",
        ),
        400,
    )


def invalid_method(request_method) -> Tuple[dict, int]:
    return (
        dict(
            result="Rejected",
            status="INVALID_METHOD",
            message="Request method %s not supported." % request_method,
        ),
        405,
    )


def invalid_role(requested_access_role: str) -> Tuple[dict, int]:
    return (
        dict(
            result="Rejected",
            status="INVALID_ROLE",
            message="No known services for specified role %s." % requested_access_role,
        ),
        400,
    )


def invalid_sender(
    user_role_names: Union[str, List[str]], *allowed_role_names: str
) -> Tuple[dict, int]:
    if isinstance(user_role_names, str):
        user_role_names = [user_role_names]
    if not user_role_names:
        user_roles_str = "have no role"
    else:
        user_role_names = [p.a(role_name) for role_name in user_role_names]
        user_roles_str = "are %s" % p.join(user_role_names)
    allowed_role_names = [pluralize(role_name) for role_name in allowed_role_names]
    allowed_role_names = p.join(allowed_role_names)
    return (
        dict(
            result="Rejected",
            status="INVALID_SENDER",
            message="You don't have the right role to access this service. "
            "You %s while this service is reserved for %s."
            % (user_roles_str, allowed_role_names),
        ),
        403,
    )


def invalid_timezone() -> Tuple[dict, int]:
    return (
        dict(
            result="Rejected",
            status="INVALID_TIMEZONE",
            message="Start time should explicitly state a timezone.",
        ),
        400,
    )


def invalid_unit(*units) -> Tuple[dict, int]:
    return (
        dict(
            result="Rejected",
            status="INVALID_UNIT",
            message="Data should be given in %s." % p.join(*units, conj="or"),
        ),
        400,
    )


def invalid_message_type(message_type: str) -> Tuple[dict, int]:
    return (
        dict(
            result="Rejected",
            status="INVALID_MESSAGE_TYPE",
            message="Request message should specify type '%s'." % message_type,
        ),
        400,
    )


def no_message_type() -> Tuple[dict, int]:
    return (
        dict(
            result="Rejected",
            status="NO_MESSAGE_TYPE",
            message="Request message should include 'type'.",
        ),
        400,
    )


def ptus_incomplete() -> Tuple[dict, int]:
    return (
        dict(result="Rejected", status="PTUS_INCOMPLETE", message="Missing values."),
        400,
    )


def unrecognized_connection_group() -> Tuple[dict, int]:
    return (
        dict(
            result="Rejected",
            status="UNRECOGNIZED_CONNECTION_GROUP",
            message="One or more connections in your request were not found in your account.",
        ),
        400,
    )


def unrecognized_sensor(lat, lng) -> Tuple[dict, int]:
    return (
        dict(
            result="Rejected",
            status="UNRECOGNIZED_SENSOR",
            message="No sensor is known at this location. The nearest sensor is at latitude %s and longitude %s"
            % (lat, lng),
        ),
        400,
    )


def request_processed() -> Tuple[dict, int]:
    return dict(status="PROCESSED", message="Request has been processed."), 200


def pluralize(usef_role_name):
    """Adding a trailing 's' works well for USEF roles."""
    return "%ss" % usef_role_name
