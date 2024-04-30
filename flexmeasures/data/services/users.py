from __future__ import annotations

import random
import string

from flask import current_app
from flask_security import current_user, SQLAlchemySessionUserDatastore
from flask_security.recoverable import update_password
from email_validator import (
    validate_email,
    EmailNotValidError,
    EmailUndeliverableError,
)
from email_validator.deliverability import validate_email_deliverability
from flask_security.utils import hash_password
from werkzeug.exceptions import NotFound
from sqlalchemy import select, delete

from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.user import User, Role, Account
from flexmeasures.utils.time_utils import server_now


class InvalidFlexMeasuresUser(Exception):
    pass


def get_user(id: str) -> User:
    """Get a user, raise if not found."""
    user: User = db.session.get(User, int(id))
    if user is None:
        raise NotFound
    return user


def get_users(
    account_name: str | None = None,
    role_name: str | None = None,
    account_role_name: str | None = None,
    only_active: bool = True,
) -> list[User]:
    """Return a list of User objects.
    The role_name parameter allows to filter by role.
    Set only_active to False if you also want non-active users.
    """
    user_query = select(User)

    if account_name is not None:
        account = db.session.execute(
            select(Account).filter_by(name=account_name)
        ).scalar_one_or_none()
        if not account:
            raise NotFound(f"There is no account named {account_name}!")
        user_query = user_query.filter_by(account=account)

    if only_active:
        user_query = user_query.filter(User.active.is_(True))

    if role_name is not None:
        role = db.session.execute(
            select(Role).filter_by(name=role_name)
        ).scalar_one_or_none()
        if role:
            user_query = user_query.filter(User.flexmeasures_roles.contains(role))

    users = db.session.scalars(user_query).all()
    if account_role_name is not None:
        users = [u for u in users if u.account.has_role(account_role_name)]

    return users


def find_user_by_email(user_email: str, keep_in_session: bool = True) -> User:
    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    user = user_datastore.find_user(email=user_email)
    if not keep_in_session:
        # we might need this object persistent across requests
        db.session.expunge(user)
    return user


def create_user(  # noqa: C901
    password: str = None,
    user_roles: dict[str, str] | list[dict[str, str]] | str | list[str] | None = None,
    check_email_deliverability: bool = True,
    account_name: str | None = None,
    **kwargs,
) -> User:
    """
    Convenience wrapper to create a new User object.

    It hashes the password.

    In addition to the user, this function can create
    - new Role objects (if user roles do not already exist)
    - an Account object (if it does not exist yet)
    - a new DataSource object that corresponds to the user

    Remember to commit the session after calling this function!
    """

    # Check necessary input explicitly before anything happens
    if password is None or password == "":
        raise InvalidFlexMeasuresUser("No password provided.")
    if "email" not in kwargs:
        raise InvalidFlexMeasuresUser("No email address provided.")
    email = kwargs.pop("email").strip()
    try:
        email_info = validate_email(email, check_deliverability=False)
        # The mx check talks to the SMTP server. During testing, we skip it because it
        # takes a bit of time and without internet connection it fails.
        if check_email_deliverability and not current_app.testing:
            try:
                validate_email_deliverability(
                    email_info.domain, email_info["domain_i18n"]
                )
            except EmailUndeliverableError as eue:
                raise InvalidFlexMeasuresUser(
                    "The email address %s does not seem to be deliverable: %s"
                    % (email, str(eue))
                )
    except EmailNotValidError as enve:
        raise InvalidFlexMeasuresUser(
            "%s is not a valid email address: %s" % (email, str(enve))
        )
    if "username" not in kwargs:
        username = email.split("@")[0]
    else:
        username = kwargs.pop("username").strip()

    # Check integrity explicitly before anything happens
    existing_user_by_email = db.session.execute(
        select(User).filter_by(email=email)
    ).scalar_one_or_none()
    if existing_user_by_email is not None:
        raise InvalidFlexMeasuresUser("User with email %s already exists." % email)
    existing_user_by_username = db.session.execute(
        select(User).filter_by(username=username)
    ).scalar_one_or_none()
    if existing_user_by_username is not None:
        raise InvalidFlexMeasuresUser(
            "User with username %s already exists." % username
        )

    # check if we can link/create an account
    if account_name is None:
        raise InvalidFlexMeasuresUser(
            "Cannot create user without knowing the name of the account which this user is associated with."
        )
    account = db.session.execute(
        select(Account).filter_by(name=account_name)
    ).scalar_one_or_none()
    active_user_id, active_user_name = None, None
    if hasattr(current_user, "id"):
        active_user_id, active_user_name = current_user.id, current_user.username
    if account is None:
        print(f"Creating account {account_name} ...")
        account = Account(name=account_name)
        db.session.add(account)
        db.session.flush()
        account_audit_log = AuditLog(
            event_datetime=server_now(),
            event=f"Account {account_name} created",
            active_user_id=active_user_id,
            active_user_name=active_user_name,
            affected_account_id=account.id,
        )
        db.session.add(account_audit_log)

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    kwargs.update(password=hash_password(password), email=email, username=username)
    user = user_datastore.create_user(**kwargs)

    user.account = account

    # add roles to user (creating new roles if necessary)
    if user_roles:
        if not isinstance(user_roles, list):
            user_roles = [user_roles]  # type: ignore
        for user_role in user_roles:
            if isinstance(user_role, dict):
                role = user_datastore.find_role(user_role["name"])
            else:
                role = user_datastore.find_role(user_role)
            if role is None:
                if isinstance(user_role, dict):
                    role = user_datastore.create_role(**user_role)
                else:
                    role = user_datastore.create_role(name=user_role)
            user_datastore.add_role_to_user(user, role)

    # create data source
    db.session.add(DataSource(user=user))
    db.session.flush()

    user_audit_log = AuditLog(
        event_datetime=server_now(),
        event=f"User {user.username} created",
        active_user_id=active_user_id,
        active_user_name=active_user_name,
        affected_user_id=user.id,
        affected_account_id=account.id,
    )
    db.session.add(user_audit_log)

    return user


def set_random_password(user: User):
    """
    Randomise a user's password.

    Remember to commit the session after calling this function!
    """
    new_random_password = "".join(
        [random.choice(string.ascii_lowercase) for _ in range(24)]
    )
    update_password(user, new_random_password)

    active_user_id, active_user_name = None, None
    if hasattr(current_user, "id"):
        active_user_id, active_user_name = current_user.id, current_user.username
    user_audit_log = AuditLog(
        event_datetime=server_now(),
        event=f"Password reset for user {user.username}",
        active_user_id=active_user_id,
        active_user_name=active_user_name,
        affected_user_id=user.id,
    )
    db.session.add(user_audit_log)


def remove_cookie_and_token_access(user: User):
    """
    Remove access of current cookies and auth tokens for a user.
    This might be useful if you feel their password, cookie or tokens
    are compromised. in the former case, you can also call `set_random_password`.

    Remember to commit the session after calling this function!
    """
    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    user_datastore.reset_user_access(user)


def delete_user(user: User):
    """
    Delete the user (and also his assets and power measurements!).

    Deleting oneself is not allowed.

    Remember to commit the session after calling this function!
    """
    if hasattr(current_user, "id") and user.id == current_user.id:
        raise Exception("You cannot delete yourself.")

    user_datastore = SQLAlchemySessionUserDatastore(db.session, User, Role)
    user_datastore.delete_user(user)
    db.session.execute(delete(User).filter_by(id=user.id))
    current_app.logger.info("Deleted %s." % user)

    active_user_id, active_user_name = None, None
    if hasattr(current_user, "id"):
        active_user_id, active_user_name = current_user.id, current_user.username
    user_audit_log = AuditLog(
        event_datetime=server_now(),
        event=f"User {user.username} deleted",
        active_user_id=active_user_id,
        active_user_name=active_user_name,
        affected_user_id=None,  # add the audit log record even if the user is gone
        affected_account_id=user.account_id,
    )
    db.session.add(user_audit_log)


def get_audit_log_records(user: User):
    """
    Get history of user actions
    """
    audit_log_records = (
        db.session.query(AuditLog).filter_by(affected_user_id=user.id).all()
    )
    return audit_log_records
