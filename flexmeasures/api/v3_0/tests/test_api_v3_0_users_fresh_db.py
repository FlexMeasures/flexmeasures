import pytest
from flask import url_for, request
from sqlalchemy import select

from flexmeasures.api.tests.utils import UserContext
from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.user import Account


@pytest.mark.parametrize(
    "requesting_user, status_code",
    [
        (None, 401),
        ("test_prosumer_user@seita.nl", 403),
        ("test_prosumer_user_2@seita.nl", 200),
        ("test_admin_user@seita.nl", 200),
        ("inactive_user@seita.nl", 401),
        ("inactive_admin@seita.nl", 401),
    ],
    indirect=["requesting_user"],
)
def test_user_reset_password(
    fresh_db, app, client, setup_inactive_user_fresh_db, requesting_user, status_code
):
    """
    Reset the password of User 2.
    Only the admin user and User 2 themselves are allowed to do that.
    """
    with UserContext("test_prosumer_user_2@seita.nl") as user2:
        user2_id = user2.id
        old_password = user2.password
    with app.mail.record_messages() as outbox:
        pwd_reset_response = client.patch(
            url_for("UserAPI:reset_user_password", id=user2_id),
            query_string={},
        )
        print("Server responded with:\n%s" % pwd_reset_response.json)

        assert pwd_reset_response.status_code == status_code
        if status_code != 200:
            return

        assert fresh_db.session.execute(
            select(AuditLog).filter_by(
                affected_user_id=user2.id,
                event=f"Password reset for user {user2.username}",
                active_user_id=requesting_user.id,
            )
        ).scalar_one_or_none()

        user2 = find_user_by_email("test_prosumer_user_2@seita.nl")
        assert len(outbox) == 2
        assert "has been reset" in outbox[0].subject
        pwd_reset_instructions = outbox[1]
        assert old_password != user2.password
        assert "reset instructions" in pwd_reset_instructions.subject
        assert (
            "reset your password:\n\n%sreset/" % request.host_url
            in pwd_reset_instructions.body
        )


#  This test can also be found in test_api_v3_0_users.py, the difference is
#  that this makes modifications to the db(and thats best to be in a seperate db session,
#  in order not to affect other tests) while the other doesn't
@pytest.mark.parametrize(
    "requesting_user, expected_status_code, user_to_update, expected_role",
    [
        # Admin updates user 4 (initially no roles) to become admin-reader & consultant
        ("test_admin_user@seita.nl", 200, 4, [3, 4]),
        # Admin updates user 5 (initially an account-admin), removing the account-admin role
        ("test_admin_user@seita.nl", 200, 5, []),
    ],
    indirect=["requesting_user"],
)
def test_user_role_successful_modification_permission(
    client,
    setup_roles_users_fresh_db,
    requesting_user,
    expected_status_code,
    user_to_update,
    expected_role,
):
    patch_user_response = client.patch(
        url_for("UserAPI:patch", id=user_to_update),
        json={"flexmeasures_roles": expected_role},
    )

    print("Server responded with:\n%s" % patch_user_response.data)
    assert patch_user_response.status_code == expected_status_code


@pytest.mark.parametrize(
    "requesting_user, account_name, status_code",
    [
        (
            "test_prosumer_user_2@seita.nl",
            "Test Prosumer Account",
            201,
        ),  # An acct-admin of "Prosumer" account
        (
            "test_dummy_account_admin@seita.nl",
            "Test Prosumer Account",
            403,
        ),  # An acct-admin of another account (Dummy account)
        (
            "test_admin_reader_user@seita.nl",
            "Test Dummy Account",
            403,
        ),  # An admin-reader of "Dummy" account
    ],
    indirect=["requesting_user"],
)
def test_user_creation_api(
    fresh_db,
    client,
    setup_roles_users_fresh_db,
    setup_accounts_fresh_db,
    requesting_user,
    account_name,
    status_code,
):
    """
    Test user creation endpoint.

    Only user with the right permissions can create a user in a certain account.
    In this case the user is required to have the "create-children" perm for that account.
    """

    account = fresh_db.session.execute(
        select(Account).filter_by(name=account_name)
    ).scalar_one()

    user_creation_response = client.post(
        url_for("UserAPI:post"),
        json={
            "email": "new_user@seita.nl",
            "username": "new_user",
            "account_id": account.id,
        },
    )
    print("Server responded with:\n%s" % user_creation_response.data)
    assert user_creation_response.status_code == status_code
