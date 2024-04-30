import pytest
from flask import url_for, request
from sqlalchemy import select

from flexmeasures.api.tests.utils import UserContext
from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.data.models.audit_log import AuditLog


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
    db, app, client, setup_inactive_user, requesting_user, status_code
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

        assert db.session.execute(
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
