from typing import List
from bvp.data.models.user import User
from inflection import pluralize, humanize
import inflect
p = inflect.engine()


def invalid_domain() -> dict:
    return dict(result='Rejected',
                status='INVALID_DOMAIN',
                message="Connections should be identified using the EA1 addressing scheme. "
                        "For example: 'ea1.2018-06.com.bvp.api:<owner-id>:<asset-id or asset-name>'")


def invalid_period() -> dict:
    return dict(result='Rejected',
                status='INVALID_PERIOD',
                message="The time period in your request doesn't seem right. "
                        "If you wish to post meter data for the future, set 'simulation' to 'true'.")


def invalid_ptu_duration() -> dict:
    return dict(result='Rejected',
                status='INVALID_PTU_DURATION',
                message="Start time should be on the hour or a multiple of 15 minutes thereafter, "
                        "duration should be some multiple N of 15 minutes, and "
                        "the number of values should be some factor of N.")


def invalid_sender(user: User, allowed_roles: List[str]) -> dict:
    user_roles = [p.a(humanize(role.name)) for role in user.roles]
    user_roles = p.join(user_roles)
    allowed_roles = [pluralize(humanize(role)) for role in allowed_roles]
    allowed_roles = p.join(allowed_roles)
    return dict(result='Rejected',
                status='INVALID_SENDER',
                message="You don't have the right role to access this service. "
                        "You are %s while this service is reserved for %s." % (user_roles, allowed_roles))


def invalid_timezone() -> dict:
    return dict(result='Rejected',
                status='INVALID_TIMEZONE',
                message="Start time should explicitly state a timezone.")


def invalid_unit() -> dict:
    return dict(result='Rejected',
                status='INVALID_UNIT',
                message="Meter data should be given in MW.")


def ptus_incomplete() -> dict:
    return dict(result='Rejected',
                status='PTUS_INCOMPLETE',
                message="Missing values.")


def unrecognized_connection_group() -> dict:
    return dict(result='Rejected',
                status='UNRECOGNIZED_CONNECTION_GROUP',
                message="One or more connections in your request were not found in your account.")
