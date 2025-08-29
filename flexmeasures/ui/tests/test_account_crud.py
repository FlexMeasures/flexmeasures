from flask import url_for
from flask_login import current_user


account_api_path = "http://localhost//api/v3_0/accounts"


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
