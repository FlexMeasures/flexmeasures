from typing import Dict, List, Union, Optional
import random
import string

from flask import current_app
from flask_security import current_user, SQLAlchemySessionUserDatastore
from flask_security.recoverable import update_password
from validate_email import validate_email

from bvp.data.config import db
from bvp.data.models.data_sources import DataSource
from bvp.data.models.user import User, Role


class InvalidBVPUser(Exception):
    pass


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

    # Check necessary input explicitly before anything happens
    if "email" not in kwargs:
        raise InvalidBVPUser("No email address provided.")
    email = kwargs.pop("email").strip()
    if validate_email(email, check_mx=False):
        if not validate_email(email, check_mx=True):
            raise InvalidBVPUser("The email address %s does not seem to exist" % email)
    else:
        raise InvalidBVPUser("%s is not a valid email address" % email)
    if "username" not in kwargs:
        username = email.split("@")[0]
    else:
        username = kwargs.pop("username").strip()

    # Check integrity explicitly before anything happens
    existing_user_by_email = User.query.filter_by(email=email).one_or_none()
    if existing_user_by_email is not None:
        raise InvalidBVPUser("User with email %s already exists." % email)
    existing_user_by_username = User.query.filter_by(username=username).one_or_none()
    if existing_user_by_username is not None:
        raise InvalidBVPUser("User with username %s already exists." % username)

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    kwargs.update(email=email, username=username)
    user = user_datastore.create_user(**kwargs)

    if user.password is None:
        new_random_password = "".join(
            [random.choice(string.ascii_lowercase) for _ in range(12)]
        )
        update_password(user, new_random_password)

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
