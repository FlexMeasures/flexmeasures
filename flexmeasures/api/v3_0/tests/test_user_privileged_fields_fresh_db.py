"""
Changing another user's email address, active status or password needs at least that user's privileges,
and an email change is announced to the previous address.
"""

import pytest
from flask import url_for
from sqlalchemy import select

from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.services.users import find_user_by_email


@pytest.mark.parametrize(
    "requesting_user, target, field, value",
    [
        # the account-admin of the Dummy account vs. the admin and admin-reader in that account
        (
            "test_dummy_account_admin@seita.nl",
            "test_admin_user@seita.nl",
            "email",
            "taken-over@example.com",
        ),
        (
            "test_dummy_account_admin@seita.nl",
            "test_admin_user@seita.nl",
            "active",
            False,
        ),
        (
            "test_dummy_account_admin@seita.nl",
            "test_admin_reader_user@seita.nl",
            "email",
            "taken-over@example.com",
        ),
        (
            "test_dummy_account_admin@seita.nl",
            "test_admin_reader_user@seita.nl",
            "active",
            False,
        ),
    ],
    indirect=["requesting_user"],
)
def test_privileged_user_fields_need_the_target_users_privileges(
    fresh_db,
    app,
    client,
    setup_roles_users_fresh_db,
    requesting_user,
    target,
    field,
    value,
):
    user = find_user_by_email(target)
    user_id, old_value = user.id, getattr(user, field)

    with app.mail.record_messages() as outbox:
        response = client.patch(
            url_for("UserAPI:patch", id=user_id), json={field: value}
        )
        reset_response = client.patch(
            url_for("UserAPI:reset_user_password", id=user_id)
        )

    assert response.status_code == 403, response.json
    assert reset_response.status_code == 403, reset_response.json
    assert not outbox
    fresh_db.session.expire_all()
    assert getattr(find_user_by_email(target), field) == old_value


@pytest.mark.parametrize(
    "requesting_user, target",
    [
        (
            "test_prosumer_user_2@seita.nl",
            "test_prosumer_user@seita.nl",
        ),  # account-admin, plain member
        (
            "test_admin_user@seita.nl",
            "test_prosumer_user_2@seita.nl",
        ),  # admin, account-admin
        (
            "test_consultant@seita.nl",
            "test_consultant_client@seita.nl",
        ),  # consultant, client user
        ("test_prosumer_user@seita.nl", "test_prosumer_user@seita.nl"),  # oneself
    ],
    indirect=["requesting_user"],
)
def test_email_change_notifies_the_previous_address(
    fresh_db, app, client, setup_roles_users_fresh_db, requesting_user, target
):
    user = find_user_by_email(target)
    user_id = user.id

    with app.mail.record_messages() as outbox:
        response = client.patch(
            url_for("UserAPI:patch", id=user_id), json={"email": "new-address@seita.nl"}
        )

    assert response.status_code == 200, response.json
    assert response.json["email"] == "new-address@seita.nl"
    assert len(outbox) == 1
    assert outbox[0].recipients == [target]
    assert "email address" in outbox[0].subject
    assert "new-address@seita.nl" in outbox[0].body
    assert fresh_db.session.execute(
        select(AuditLog).filter_by(
            affected_user_id=user_id,
            active_user_id=requesting_user.id,
            # 1.0.x records the change itself, without naming the user (that is the affected_user_id)
            event=f"Email changed from '{target}' to 'new-address@seita.nl'. ",
        )
    ).scalar_one_or_none()


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_unchanged_email_sends_no_notice(
    fresh_db, app, client, setup_roles_users_fresh_db, requesting_user
):
    user = find_user_by_email("test_prosumer_user@seita.nl")
    with app.mail.record_messages() as outbox:
        response = client.patch(
            url_for("UserAPI:patch", id=user.id),
            json={"email": user.email, "username": "Renamed"},
        )
    assert response.status_code == 200, response.json
    assert not outbox
