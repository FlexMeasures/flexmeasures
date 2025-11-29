from flask import url_for

from flexmeasures.data.services.users import find_user_by_email


"""
Testing if the UI crud views do auth checks and display answers.
Actual logic is tested in the API tests.
"""


def test_user_list(client, as_admin):
    user_index = client.get(url_for("UserCrudUI:index"), follow_redirects=True)
    assert user_index.status_code == 200
    assert b"All active users" in user_index.data


def test_user_page_as_nonadmin_from_other_account(client, as_prosumer_user1):
    dummy_user_id = find_user_by_email("test_dummy_user_3@seita.nl").id
    user_page = client.get(
        url_for("UserCrudUI:get", id=dummy_user_id), follow_redirects=True
    )
    assert user_page.status_code == 403


def test_user_page(client, as_admin, setup_accounts):
    user2 = find_user_by_email("test_prosumer_user_2@seita.nl")
    user_page = client.get(
        url_for("UserCrudUI:get", id=user2.id), follow_redirects=True
    )
    assert user_page.status_code == 200
    assert ("User: %s" % user2.username).encode() in user_page.data
    assert (f">{user2.account.number_of_assets}</a>").encode() in user_page.data
    assert user2.email.encode() in user_page.data


def test_reset_password(client, as_admin):
    """Test it does not fail (logic is tested in API tests) and displays an answer."""
    user2 = find_user_by_email("test_prosumer_user_2@seita.nl", keep_in_session=False)
    user_page = client.get(
        url_for("UserCrudUI:reset_password_for", id=user2.id),
        follow_redirects=True,
    )
    assert user_page.status_code == 200
    assert b"has been changed to a random password" in user_page.data
