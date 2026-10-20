"""Plan quota and consultancy restrictions through public API paths."""

import pytest
from flask import url_for
from sqlalchemy import func, select
from werkzeug.exceptions import UnprocessableEntity

from flexmeasures.api.common.utils.api_utils import copy_asset
from flexmeasures.api.v3_0.tests.utils import get_asset_post_data
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.user import Account, AccountRole, Plan, Role, User
from flexmeasures.data.services.users import find_user_by_email


def _assign_plan(db, account: Account, **limits) -> None:
    account.plan = Plan(name="Free", **limits)
    db.session.commit()


def test_new_organisation_enforces_zero_user_quota_before_first_flush(fresh_db):
    """Creating the organisation and user together must not bypass a zero quota."""
    plan = Plan(name="No users", max_users=0)
    fresh_db.session.add(plan)
    fresh_db.session.commit()
    account = Account(name="Empty free account", plan_id=plan.id)
    user = User(
        email="initial@example.com",
        username="initial",
        password="test",
        fs_uniquifier="initial-test-user",
        account=account,
    )
    fresh_db.session.add_all([account, user])

    with pytest.raises(UnprocessableEntity, match="at most 0 users"):
        fresh_db.session.flush()


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_user_quota_rejects_creation_at_boundary(
    fresh_db,
    client,
    setup_roles_users_fresh_db,
    setup_accounts_fresh_db,
    requesting_user,
):
    account = setup_accounts_fresh_db["Prosumer"]
    _assign_plan(fresh_db, account, max_users=3)

    response = client.post(
        url_for("UserAPI:post"),
        json={
            "email": "new_free_user@example.com",
            "username": "new_free_user",
            "account_id": account.id,
        },
    )

    assert response.status_code == 422, response.json
    assert "at most 3 users" in response.json["message"]
    fresh_db.session.rollback()
    assert (
        fresh_db.session.scalar(
            select(func.count(User.id)).where(User.account_id == account.id)
        )
        == 3
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_asset_quota_rejects_creation_and_subtree_copy(
    fresh_db,
    client,
    setup_roles_users_fresh_db,
    setup_generic_assets_fresh_db,
    setup_generic_asset_types_fresh_db,
    setup_accounts_fresh_db,
    requesting_user,
):
    account = setup_accounts_fresh_db["Prosumer"]
    source = setup_generic_assets_fresh_db["test_battery"]
    child = GenericAsset(
        name="Battery child",
        generic_asset_type=source.generic_asset_type,
        owner=account,
        parent_asset=source,
    )
    fresh_db.session.add(child)
    fresh_db.session.commit()
    _assign_plan(fresh_db, account, max_assets=2)

    response = client.post(
        url_for("AssetAPI:post"),
        json=get_asset_post_data(
            account.id, setup_generic_asset_types_fresh_db["battery"].id
        ),
    )
    assert response.status_code == 422, response.json
    assert "at most 2 assets" in response.json["message"]
    fresh_db.session.rollback()

    # The copied root fits; its child would exceed the quota. Roll back both.
    account.plan.max_assets = 3
    fresh_db.session.commit()
    with pytest.raises(UnprocessableEntity, match="at most 3 assets"):
        copy_asset(source, account=account)
    assert (
        fresh_db.session.scalar(
            select(func.count(GenericAsset.id)).where(
                GenericAsset.account_id == account.id
            )
        )
        == 2
    )


@pytest.mark.parametrize("requesting_user", ["test_consultant@seita.nl"], indirect=True)
def test_zero_client_quota_rejects_client_creation(
    fresh_db,
    client,
    setup_roles_users_fresh_db,
    setup_accounts_fresh_db,
    requesting_user,
):
    consultancy = setup_accounts_fresh_db["Consultancy"]
    _assign_plan(fresh_db, consultancy, max_clients=0)

    response = client.post(url_for("AccountAPI:post"), json={"name": "New client"})

    assert response.status_code == 422, response.json
    assert "at most 0 client organisations" in response.json["message"]
    fresh_db.session.rollback()
    assert (
        fresh_db.session.scalar(select(Account.id).where(Account.name == "New client"))
        is None
    )


@pytest.mark.parametrize(
    "requesting_user", ["test_prosumer_user_2@seita.nl"], indirect=True
)
def test_zero_client_plan_rejects_consultancy_role_escalation(
    fresh_db,
    client,
    setup_roles_users_fresh_db,
    setup_accounts_fresh_db,
    requesting_user,
):
    account = setup_accounts_fresh_db["Prosumer"]
    _assign_plan(fresh_db, account, max_clients=0)
    consultancy_role = fresh_db.session.scalar(
        select(AccountRole).where(AccountRole.name == "Consultancy")
    )
    if consultancy_role is None:
        consultancy_role = AccountRole(name="Consultancy")
        fresh_db.session.add(consultancy_role)
        fresh_db.session.commit()

    response = client.patch(
        url_for("AccountAPI:patch", id=account.id),
        json={
            "account_roles": [
                *(role.id for role in account.account_roles),
                consultancy_role.id,
            ]
        },
    )
    assert response.status_code == 422, response.json
    fresh_db.session.rollback()
    assert all(role.name != "Consultancy" for role in account.account_roles)

    consultant_role = fresh_db.session.scalar(
        select(Role).where(Role.name == "consultant")
    )
    colleague = find_user_by_email("test_prosumer_user@seita.nl")
    response = client.patch(
        url_for("UserAPI:patch", id=colleague.id),
        json={
            "flexmeasures_roles": [
                *(role.id for role in colleague.flexmeasures_roles),
                consultant_role.id,
            ]
        },
    )
    assert response.status_code == 422, response.json
    fresh_db.session.rollback()
    assert all(role.name != "consultant" for role in colleague.flexmeasures_roles)


def test_relationship_transfers_cannot_bypass_destination_quotas(
    fresh_db,
    setup_roles_users_fresh_db,
    setup_generic_assets_fresh_db,
    setup_accounts_fresh_db,
):
    """Changing an ORM relationship checks the destination before its FK is synced."""
    prosumer = setup_accounts_fresh_db["Prosumer"]
    _assign_plan(fresh_db, prosumer, max_users=3, max_assets=1, max_clients=0)

    supplier_asset = setup_generic_assets_fresh_db["test_wind_turbine"]
    supplier_asset.owner = prosumer
    with pytest.raises(UnprocessableEntity, match="at most 1 asset"):
        fresh_db.session.flush()
    fresh_db.session.rollback()

    supplier_user = find_user_by_email("test_supplier_user_4@seita.nl")
    supplier_user.account = prosumer
    with pytest.raises(UnprocessableEntity, match="at most 3 users"):
        fresh_db.session.flush()
    fresh_db.session.rollback()

    client_account = setup_accounts_fresh_db["ConsultancyClient"]
    client_account.consultancy_account = prosumer
    with pytest.raises(UnprocessableEntity, match="at most 0 client organisations"):
        fresh_db.session.flush()
    fresh_db.session.rollback()


def test_fk_only_user_creation_cannot_gain_consultant_role(
    fresh_db, setup_roles_users_fresh_db, setup_accounts_fresh_db
):
    prosumer = setup_accounts_fresh_db["Prosumer"]
    _assign_plan(fresh_db, prosumer, max_users=4, max_clients=0)
    consultant = fresh_db.session.scalar(select(Role).where(Role.name == "consultant"))
    user = User(
        email="new_consultant@example.com",
        username="new_consultant",
        password="test",
        fs_uniquifier="new-consultant-test-user",
        account_id=prosumer.id,
        flexmeasures_roles=[consultant],
    )
    fresh_db.session.add(user)

    with pytest.raises(UnprocessableEntity, match="consultancy privileges"):
        fresh_db.session.flush()


def test_existing_consultant_cannot_move_to_zero_client_plan(
    fresh_db, setup_roles_users_fresh_db, setup_accounts_fresh_db
):
    prosumer = setup_accounts_fresh_db["Prosumer"]
    _assign_plan(fresh_db, prosumer, max_users=4, max_clients=0)
    consultant = find_user_by_email("test_consultant@seita.nl")
    consultant.account_id = prosumer.id

    with pytest.raises(UnprocessableEntity, match="consultancy privileges"):
        fresh_db.session.flush()


def test_changed_plan_id_is_enforced_before_flush(
    fresh_db, setup_generic_assets_fresh_db, setup_accounts_fresh_db
):
    prosumer = setup_accounts_fresh_db["Prosumer"]
    old_plan = Plan(name="Uncapped")
    free_plan = Plan(name="Free", max_assets=1)
    prosumer.plan = old_plan
    fresh_db.session.add(free_plan)
    fresh_db.session.commit()
    assert prosumer.plan is old_plan  # keep the old relationship loaded

    prosumer.plan_id = free_plan.id
    fresh_db.session.add(
        GenericAsset(
            name="Another asset",
            owner=prosumer,
            generic_asset_type=setup_generic_assets_fresh_db[
                "test_battery"
            ].generic_asset_type,
        )
    )
    with pytest.raises(UnprocessableEntity, match="at most 1 asset"):
        fresh_db.session.flush()
