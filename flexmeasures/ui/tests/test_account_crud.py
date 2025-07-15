from flask import url_for
from flask_login import current_user
from flexmeasures.ui.views.accounts import get_accounts, get_account
from flexmeasures.ui.tests.utils import mock_account_response


account_api_path = "http://localhost//api/v3_0/accounts"


def test_get_accounts_as_nonadmin(client, as_prosumer_user1, requests_mock):
    requests_mock.get(
        account_api_path,
        status_code=200,
        json=mock_account_response(multiple=False),
    )
    assert get_accounts() == [
        {
            "id": 1,
            "name": "test_account",
            "account_roles": [{"id": 1, "name": "Prosumer"}],
        }
    ]


def test_get_accounts_as_admin(client, as_admin, requests_mock):
    requests_mock.get(
        account_api_path,
        status_code=200,
        json=mock_account_response(multiple=True),
    )
    assert get_accounts() == [
        {
            "id": 1,
            "name": "test_account",
            "account_roles": [{"id": 1, "name": "Prosumer"}],
        },
        {"id": 2, "name": "test_account2", "account_roles": []},
    ]


def test_get_account_as_admin(client, as_admin, requests_mock):
    mock_account = mock_account_response(as_list=False)
    requests_mock.get(
        f"{account_api_path}/1",
        status_code=200,
        json=mock_account,
    )
    assert get_account(account_id="1") == {
        "id": 1,
        "name": "test_account",
        "account_roles": [{"id": 1, "name": "Prosumer"}],
    }


def test_get_account_as_nonadmin(client, as_prosumer_user1, requests_mock):
    mock_account = mock_account_response(as_list=False)
    requests_mock.get(
        f"{account_api_path}/{current_user.account.id}",
        status_code=200,
        json=mock_account,
    )
    assert get_account(account_id=current_user.account.id) == {
        "id": current_user.account.id,
        "name": "test_account",
        "account_roles": [{"id": 1, "name": "Prosumer"}],
    }


def test_account_page(db, client, requests_mock, as_prosumer_user1):
    prosumer_account_info = {
        "id": current_user.account.id,
        "name": "test_account",
        "account_roles": [{"id": 1, "name": "Prosumer"}],
    }
    requests_mock.get(
        f"{account_api_path}/{current_user.account_id}",
        status_code=200,
        json=prosumer_account_info,
    )
    account_page = client.get(
        url_for("AccountCrudUI:get", account_id=current_user.account_id),
        follow_redirects=True,
    )
    assert account_page.status_code == 200
    assert str(f"Account: {current_user.account.name}") in str(account_page.data)
    assert b"All users" in account_page.data
    assert str(current_user.username) in str(account_page.data)
