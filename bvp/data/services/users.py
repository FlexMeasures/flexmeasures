from typing import Dict, List, Union, Optional

from flask import current_app
from flask_security import current_user, SQLAlchemySessionUserDatastore

from bvp.data.config import db
from bvp.data.models.data_sources import DataSource
from bvp.data.models.user import User, Role


def get_users(role_name: Optional[str] = None, only_active: bool = True) -> List[User]:
    """Return a list of User objects.
       The role_name parameter allows to filter by role.
       Set only_active to False if you also want non-active users.
    """
    user_query = User.query
    if only_active:
        user_query = user_query.filter(User.active.is_(True))

    if role_name is not None:
        role = Role.query.filter(Role.name == role_name).one_or_none()
        if role:
            user_query = user_query.filter(User.roles.contains(role))

    return user_query.all()


def find_user_by_email(user_email: str) -> User:
    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    return user_datastore.find_user(email=user_email)


def create_user(
    user_roles: Union[Dict[str, str], List[Dict[str, str]], str, List[str]] = None,
    **kwargs
) -> User:
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
    db.session.commit()  # Todo: try to handle all transactions in one session, rather than one session per user created

    return user


def toggle_activation_status_of(user: User):
    """Toggle the active attribute of user"""
    user.active = not user.active
    db.session.commit()


def delete_user(user: User):
    """Delete the user (and also his assets and power measurements!). Deleting oneself is not allowed."""
    if hasattr(current_user, "id") and user.id == current_user.id:
        raise Exception("You cannot delete yourself.")
    else:
        user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
        user_datastore.delete_user(user)
        db.session.delete(user)
        db.session.commit()  # Todo: try to handle all transactions in one session
        current_app.logger.info("Deleted %s." % user)
