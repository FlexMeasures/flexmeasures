from typing import List

from bvp.data.models.user import User, Role


def get_users(role_name: str) -> List[User]:
    """Return a list of all User objects for which one of the roles is the specified role name."""
    if not role_name:
        return User.query.all()
    role = Role.query.filter(Role.name == role_name).one_or_none()  # Look up role
    if role:
        return User.query.filter(User.roles.contains(role)).all()
    else:
        return list()
