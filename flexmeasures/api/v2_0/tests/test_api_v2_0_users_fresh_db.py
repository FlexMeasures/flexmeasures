import pytest
from flask import url_for, request

from flexmeasures.api.tests.utils import UserContext, get_auth_token
from flexmeasures.data.services.users import find_user_by_email


@pytest.mark.parametrize(
    "sender",
    (
        (""),
        ("test_prosumer_user@seita.nl"),
        ("test_prosumer_user_2@seita.nl"),
        ("test_admin_user@seita.nl"),
        ("inactive@seita.nl"),
    ),
)
def test_user_reset_password(app, client, setup_inactive_user, sender):
    """
    Reset the password of User 2.
    Only the admin user and User 2 themselves are allowed to do that.
    """
    with UserContext("test_prosumer_user_2@seita.nl") as user2:
        user2_id = user2.id
        old_password = user2.password
    headers = {"content-type": "application/json"}
    if sender != "":
        headers["Authorization"] = (get_auth_token(client, sender, "testtest"),)
    with app.mail.record_messages() as outbox:
        pwd_reset_response = client.patch(
            url_for("flexmeasures_api_v2_0.reset_user_password", id=user2_id),
            query_string={},
            headers=headers,
        )
        print("Server responded with:\n%s" % pwd_reset_response.json)

        if sender in ("", "inactive@seita.nl"):
            assert pwd_reset_response.status_code == 401
            return
        if sender == "test_prosumer_user@seita.nl":
            assert pwd_reset_response.status_code == 403
            return

        assert pwd_reset_response.status_code == 200

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
