"""Plan usage display on the organisation page."""

from flask import url_for

from flexmeasures.data.models.user import Plan
from flexmeasures.data.services.users import find_user_by_email
from flexmeasures.ui.tests.utils import login


def test_account_plan_tooltip_shows_quota_usage(
    fresh_db,
    client,
    setup_accounts_fresh_db,
    setup_roles_users_fresh_db,
    setup_generic_assets_fresh_db,
):
    """The existing plan tooltip pairs current usage with each quota."""
    account = setup_accounts_fresh_db["Prosumer"]
    account.plan = Plan(name="Free", max_users=5, max_assets=12, max_clients=0)
    find_user_by_email("test_prosumer_user_2@seita.nl").active = False
    fresh_db.session.commit()
    login(client, "test_prosumer_user@seita.nl", "testtest")

    page = client.get(url_for("AccountCrudUI:get", account_id=account.id))

    assert page.status_code == 200
    assert b"Active users: 2 / 5" in page.data
    assert b"Assets: 1 / 12" in page.data
    assert b"Client organisations: 0 / 0" in page.data
