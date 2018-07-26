from typing import Dict, List, Union

from flask_security import SQLAlchemySessionUserDatastore

from bvp.data.config import db
from bvp.data.models.data_sources import DataSource
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


def create_user(
    user_roles: Union[Dict[str, str], List[Dict[str, str]], str, List[str]] = None,
    **kwargs
):
    """Convenience wrapper to create a new User object and new Role objects (if user roles do not already exist),
    and new DataSource object that corresponds to the user."""

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)

    # create user
    user = user_datastore.create_user(**kwargs)

    # add roles to user (creating new roles if necessary)
    if user_roles:
        if not isinstance(user_roles, list):
            user_roles = [user_roles]
        for user_role in user_roles:
            if isinstance(user_role, dict):
                role = user_datastore.find_role(user_role["name"])
            else:
                role = user_datastore.find_role(user_role)
            if role is None:
                role = user_datastore.create_role(**user_role)
            user_datastore.add_role_to_user(user, role)

    # create data source
    db.session.add(
        DataSource(
            label="data entered by user %s" % user.username,
            type="user",
            user_id=user.id,
        )
    )

    return user
