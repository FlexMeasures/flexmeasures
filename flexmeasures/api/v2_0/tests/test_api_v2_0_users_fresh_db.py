import pytest
from flask import url_for, request

from flexmeasures.api.tests.utils import UserContext, get_auth_token
from flexmeasures.data.services.users import find_user_by_email


@pytest.mark.parametrize(
    "sender",
    (
        (""),
        ("test_supplier@seita.nl"),
        ("test_prosumer@seita.nl"),
        ("inactive@seita.nl"),
    ),
)
def test_user_reset_password(app, client, setup_inactive_user, sender):
    """
    Reset the password of supplier.
    Only the prosumer (as admin) and the supplier themselves are allowed to do that.
    """
    with UserContext("test_supplier@seita.nl") as supplier:
        supplier_id = supplier.id
        old_password = supplier.password
    headers = {"content-type": "application/json"}
    if sender != "":
        headers["Authorization"] = (get_auth_token(client, sender, "testtest"),)
    with app.mail.record_messages() as outbox:
        pwd_reset_response = client.patch(
            url_for("flexmeasures_api_v2_0.reset_user_password", id=supplier_id),
            query_string={},
            headers=headers,
        )
        print("Server responded with:\n%s" % pwd_reset_response.json)

        if sender in ("", "inactive@seita.nl"):
            assert pwd_reset_response.status_code == 401
            return

        assert pwd_reset_response.status_code == 200

        supplier = find_user_by_email("test_supplier@seita.nl")
        assert len(outbox) == 2
        assert "has been reset" in outbox[0].subject
        pwd_reset_instructions = outbox[1]
        assert old_password != supplier.password
        assert "reset instructions" in pwd_reset_instructions.subject
        assert (
            "reset your password:\n\n%sreset/" % request.host_url
            in pwd_reset_instructions.body
        )
