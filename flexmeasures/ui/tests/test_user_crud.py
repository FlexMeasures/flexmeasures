import pytest
from flask import url_for
from flask_login import current_user

from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.ui.tests.utils import mock_user_response
from flexmeasures.ui.crud.users import get_users_by_account


"""
Testing if the UI crud views do auth checks and display answers.
Actual logic is tested in the API tests.
"""


def test_get_users_by_account(client, requests_mock, as_prosumer_user1):
    requests_mock.get(
        "http://localhost//api/v3_0/users",
        status_code=200,
        json=mock_user_response(multiple=True),
    )
    assert get_users_by_account(current_user.account.id)[0].username == "Alex"


def test_user_list(client, as_admin, requests_mock):
    requests_mock.get(
        "http://localhost//api/v3_0/users",
        status_code=200,
        json=mock_user_response(multiple=True),
    )
    user_index = client.get(url_for("UserCrudUI:index"), follow_redirects=True)
    assert user_index.status_code == 200
    assert b"All active users" in user_index.data
    assert b"alex@seita.nl" in user_index.data
    assert b"bert@seita.nl" in user_index.data


@pytest.mark.parametrize("view", ["get", "toggle_active"])
def test_user_page_as_nonadmin(client, as_prosumer_user1, view):
    user2_id = find_user_by_email("test_prosumer_user_2@seita.nl").id
    user_page = client.get(
        url_for(f"UserCrudUI:{view}", id=user2_id), follow_redirects=True
    )
    assert user_page.status_code == 403


def test_user_page(client, as_admin, requests_mock):
    mock_user = mock_user_response(as_list=False)
    requests_mock.get(
        "http://localhost//api/v3_0/users/2", status_code=200, json=mock_user
    )
    requests_mock.get(
        "http://localhost//api/v3_0/assets",
        status_code=200,
        json=[{}, {}, {}],  # we only care about the length
    )
    user_page = client.get(url_for("UserCrudUI:get", id=2), follow_redirects=True)
    assert user_page.status_code == 200
    assert ("User: %s" % mock_user["username"]).encode() in user_page.data
    assert (">3</a>").encode() in user_page.data  # this is the asset count
    assert mock_user["email"].encode() in user_page.data


def test_deactivate_user(client, as_admin, requests_mock):
    """Test it does not fail (logic is tested in API tests) and displays an answer."""
    user2 = find_user_by_email("test_prosumer_user_2@seita.nl", keep_in_session=False)
    requests_mock.patch(
        f"http://localhost//api/v3_0/users/{user2.id}",
        status_code=200,
        json={"active": False},
    )
    # de-activate
    user_page = client.get(
        url_for("UserCrudUI:toggle_active", id=user2.id), follow_redirects=True
    )
    assert user_page.status_code == 200
    assert user2.username in str(user_page.data)
    assert b"new activation status is now False" in user_page.data


def test_reset_password(client, as_admin, requests_mock):
    """Test it does not fail (logic is tested in API tests) and displays an answer."""
    user2 = find_user_by_email("test_prosumer_user_2@seita.nl", keep_in_session=False)
    requests_mock.patch(
        f"http://localhost//api/v3_0/users/{user2.id}/password-reset",
        status_code=200,
    )
    user_page = client.get(
        url_for("UserCrudUI:reset_password_for", id=user2.id),
        follow_redirects=True,
    )
    assert user_page.status_code == 200
    assert b"has been changed to a random password" in user_page.data
