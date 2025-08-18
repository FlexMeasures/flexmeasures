from werkzeug.exceptions import Forbidden, Unauthorized
from sqlalchemy import select
import flask_login.utils
import pytest

from flexmeasures.auth.policy import check_access
from flexmeasures import Sensor
from flexmeasures.data.models.user import User, Account
from flexmeasures.data.models.generic_assets import GenericAsset


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
    "requesting_user, required_perm, account_name, has_perm",
    [
        ("test_consultant@seita.nl", "update", "Test ConsultancyClient Account", True),
        ("test_consultant@seita.nl", "update", "Test Supplier Account", False),
        (
            "test_consultant@seita.nl",
            "create-children",
            "Test ConsultancyClient Account",
            True,
        ),
        ("test_consultant@seita.nl", "create-children", "Test Supplier Account", False),
    ],
)
def test_consultant_can_work_on_clients_account(
    db,
    monkeypatch,
    setup_roles_users,
    requesting_user,
    required_perm,
    account_name,
    has_perm,
):
    with monkeypatch.context() as m:
        set_current_user(db, m, requesting_user)

        account = db.session.execute(
            select(Account).filter_by(name=account_name)
        ).scalar_one_or_none()

        try:
            result = check_access(account, required_perm)
            if result is None:
                has_access = True
        except (Forbidden, Unauthorized):
            has_access = False

        assert has_access == has_perm


@pytest.mark.parametrize(
    "requesting_user, required_perm, account_name, has_perm",
    [
        ("test_consultant@seita.nl", "delete", "Test ConsultancyClient Account", True),
        ("test_consultant@seita.nl", "delete", "Test Prosumer Account", False),
        ("test_consultant@seita.nl", "update", "Test ConsultancyClient Account", True),
        ("test_consultant@seita.nl", "update", "Test Prosumer Account", False),
        (
            "test_consultant@seita.nl",
            "create-children",
            "Test ConsultancyClient Account",
            True,
        ),
        ("test_consultant@seita.nl", "create-children", "Test Prosumer Account", False),
    ],
)
def test_consultant_can_work_on_clients_sensor(
    db,
    monkeypatch,
    setup_accounts,
    add_battery_assets,
    add_consultancy_assets,
    requesting_user,
    required_perm,
    account_name,
    has_perm,
):
    account = db.session.execute(
        select(Account).filter_by(name=account_name)
    ).scalar_one_or_none()

    sensor = (
        db.session.execute(
            select(Sensor)
            .join(GenericAsset)
            .where(GenericAsset.account_id == account.id)
        )
        .scalars()
        .first()
    )

    with monkeypatch.context() as m:
        set_current_user(db, m, requesting_user)

        try:
            result = check_access(sensor, required_perm)
            if result is None:
                has_access = True
        except (Forbidden, Unauthorized):
            has_access = False

        assert has_access == has_perm


@pytest.mark.parametrize(
    "requesting_user, required_perm, account_name, has_perm",
    [
        ("test_consultant@seita.nl", "delete", "Test ConsultancyClient Account", True),
        ("test_consultant@seita.nl", "delete", "Test Prosumer Account", False),
        ("test_consultant@seita.nl", "update", "Test ConsultancyClient Account", True),
        ("test_consultant@seita.nl", "update", "Test Prosumer Account", False),
        (
            "test_consultant@seita.nl",
            "create-children",
            "Test ConsultancyClient Account",
            True,
        ),
        ("test_consultant@seita.nl", "create-children", "Test Prosumer Account", False),
    ],
)
def test_consultant_can_work_on_clients_asset(
    db,
    monkeypatch,
    setup_accounts,
    add_battery_assets,
    add_consultancy_assets,
    requesting_user,
    required_perm,
    account_name,
    has_perm,
):

    account = db.session.execute(
        select(Account).filter_by(name=account_name)
    ).scalar_one_or_none()

    if account.number_of_assets > 0:
        asset = (
            db.session.execute(select(GenericAsset).filter_by(account_id=account.id))
            .scalars()
            .first()
        )
        with monkeypatch.context() as m:
            set_current_user(db, m, requesting_user)
            try:
                result = check_access(asset, required_perm)
                if result is None:
                    has_access = True
            except (Forbidden, Unauthorized):
                has_access = False

            assert has_access == has_perm
    else:
        assert has_perm is None, "No assets available for this account to delete."
