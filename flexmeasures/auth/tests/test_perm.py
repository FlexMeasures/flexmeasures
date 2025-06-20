from werkzeug.exceptions import Forbidden, Unauthorized
from sqlalchemy import select
import flask_login.utils
import pytest

from flexmeasures.auth.policy import check_access
from flexmeasures.data.models.user import User, Account


def set_current_user(db, monkeypatch, requested_user_email):
    """Set the current user in the Flask app context."""

    user = db.session.execute(
        select(User).filter_by(email=requested_user_email)
    ).scalar_one_or_none()

    monkeypatch.setattr(flask_login.utils, "_get_user", lambda: user)

    return user


@pytest.mark.parametrize(
    "requesting_user, requested_user, required_perm, has_perm",
    [
        # Consultant tries to update client user
        ("test_consultant@seita.nl", "test_consultant_client@seita.nl", "update", True),
        # Consultant tries to update user from another client
        (
            "test_consultant@seita.nl",
            "test_admin_reader_user@seita.nl",
            "update",
            False,
        ),
    ],
)
def test_consultant_user_update_perm(
    db,
    monkeypatch,
    setup_roles_users,
    requesting_user,
    requested_user,
    required_perm,
    has_perm,
):

    requested_user = db.session.execute(
        select(User).filter_by(email=requested_user)
    ).scalar_one_or_none()

    with monkeypatch.context() as m:
        set_current_user(db, m, requesting_user)

        try:
            result = check_access(requested_user, required_perm)
            if result is None:
                has_access = True
        except (Forbidden, Unauthorized):
            has_access = False

        assert has_access == has_perm


@pytest.mark.parametrize(
    "requesting_user, account_name, has_perm",
    [
        # Consultant tries to update client account
        ("test_consultant@seita.nl", "Test ConsultancyClient Account", True),
        # Consultant tries to update account from another client
        ("test_consultant@seita.nl", "Test Supplier Account", False),
    ],
)
def test_consultant_account_update_perm(
    db,
    monkeypatch,
    setup_roles_users,
    requesting_user,
    account_name,
    has_perm,
):
    with monkeypatch.context() as m:
        set_current_user(db, m, requesting_user)

        account = db.session.execute(
            select(Account).filter_by(name=account_name)
        ).scalar_one_or_none()

        try:
            result = check_access(account, "update")
            if result is None:
                has_access = True
        except (Forbidden, Unauthorized):
            has_access = False

        assert has_access == has_perm


@pytest.mark.parametrize(
    "requesting_user, has_perm",
    [
        # Consultant tries to create client account
        ("test_consultant@seita.nl", True),
    ],
)
def test_consultant_account_create_children_perm(
    db,
    monkeypatch,
    setup_roles_users,
    requesting_user,
    has_perm,
):
    with monkeypatch.context() as m:
        current_user = set_current_user(db, m, requesting_user)
        client_accounts = current_user.account.consultancy_client_accounts
        account = client_accounts[0]
        try:
            result = check_access(account, "create-children")
            if result is None:
                has_access = True
        except (Forbidden, Unauthorized):
            has_access = False

        assert has_access == has_perm
