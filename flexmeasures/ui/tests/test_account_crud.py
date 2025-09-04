from flask import url_for
from flask_login import current_user


account_api_path = "http://localhost//api/v3_0/accounts"


def test_account_page(db, client, as_prosumer_user1):
    account_page = client.get(
        url_for("AccountCrudUI:get", account_id=current_user.account_id),
        follow_redirects=True,
    )
    assert account_page.status_code == 200
    assert str(f"Account: {current_user.account.name}") in str(account_page.data)
    assert b"All users" in account_page.data
    assert str(current_user.username) in str(account_page.data)
