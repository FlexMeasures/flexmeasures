from flask_login import current_user
from flask import url_for
from flexmeasures.ui.crud.api_wrapper import InternalApi
from flexmeasures.ui.crud.accounts import get_accounts, get_account
from flexmeasures.ui.tests.utils import mock_account_response


def test_account_list(client, as_admin, requests_mock):
    requests_mock.get(
        "http://localhost//api/v3_0/accounts",
        status_code=200,
        json=mock_account_response(multiple=True),
    )
    requests_mock.get(
        "http://localhost//api/v3_0/accounts/1",
        status_code=200,
        json=mock_account_response(multiple=True),
    )
    account_index = InternalApi().get(url_for("AccountAPI:index"))

    get_accounts_response = InternalApi().get(url_for("AccountAPI:get", id=1))
    print(get_accounts_response)
    assert account_index.status_code == 200
    # assert 1==2


def test_account(client, as_admin, requests_mock):
    mock_account = mock_account_response(as_list=False)
    requests_mock.get(
        "http://localhost//api/v3_0/accounts/1",
        status_code=200,
        json=mock_account,
    )

    get_account_response = InternalApi().get(url_for("AccountAPI:get", id=1))
    print(get_account_response.json())
    print(current_user.account)
    # assert 1 == 2


def test_get_accounts(client, as_admin, requests_mock):
    requests_mock.get(
        "http://localhost//api/v3_0/accounts",
        status_code=200,
        json=mock_account_response(multiple=True),
    )
    accounts = get_accounts()
    print(accounts)
    assert get_accounts() == [
        {"id": 1, "name": "test_account", "account_roles": []},
        {
            "id": 2,
            "name": "test_account",
            "account_roles": [],
            "account_name": "test_account2",
        },
    ]


def test_get_account(client, as_admin, requests_mock):
    mock_account = mock_account_response(as_list=False)
    requests_mock.get(
        "http://localhost//api/v3_0/accounts/1",
        status_code=200,
        json=mock_account,
    )
    assert get_account(account_id="1") == {
        "id": 1,
        "name": "test_account",
        "account_roles": [],
    }
