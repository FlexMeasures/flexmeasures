"""Plan quota and consultancy restrictions through public API paths."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from flask import url_for
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session
from flexmeasures.data.services.plan_quotas import (
    PlanQuotaExceeded,
    _enforce_existing_account_quotas,
)

from flexmeasures.api.common.utils.api_utils import copy_asset
from flexmeasures.api.v3_0.tests.utils import get_asset_post_data
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.user import Account, AccountRole, Plan, Role, User
from flexmeasures.data.services.users import find_user_by_email


def _assign_plan(db, account: Account, **limits) -> None:
    account.plan = Plan(name="Free", **limits)
    db.session.commit()


def test_lock_only_organisations_with_relevant_quotas(
    fresh_db, setup_accounts_fresh_db, setup_generic_asset_types_fresh_db
):
    no_plan = setup_accounts_fresh_db["Prosumer"]
    unrelated_quota = setup_accounts_fresh_db["Supplier"]
    limited = setup_accounts_fresh_db["Dummy"]
    unrelated_quota.plan = Plan(name="Users only", max_users=1)
    limited.plan = Plan(name="Asset limit", max_assets=1)
    fresh_db.session.commit()
    asset_type = setup_generic_asset_types_fresh_db["battery"]
    account_ids = [no_plan.id, unrelated_quota.id, limited.id]
    asset_type_id = asset_type.id
    locks = []

    def capture_lock(connection, cursor, statement, parameters, context, executemany):
        if "FOR UPDATE" in statement.upper():
            locks.append((statement, parameters))

    engine = fresh_db.engine
    event.listen(engine, "before_cursor_execute", capture_lock)
    try:
        for index, account_id in enumerate(account_ids[:2]):
            fresh_db.session.add(
                GenericAsset(
                    name=f"Unlimited asset {index}",
                    account_id=account_id,
                    generic_asset_type_id=asset_type_id,
                )
            )
        fresh_db.session.flush()
        assert not locks

        fresh_db.session.add(
            GenericAsset(
                name="Limited asset",
                account_id=account_ids[2],
                generic_asset_type_id=asset_type_id,
            )
        )
        fresh_db.session.add(
            GenericAsset(
                name="Another unlimited asset",
                account_id=account_ids[0],
                generic_asset_type_id=asset_type_id,
            )
        )
        fresh_db.session.flush()
        assert len(locks) == 1
        assert set(locks[0][1].values()) == {account_ids[2]}

        # A quota changed in the same flush must be considered before selecting locks.
        unrelated_quota.plan.max_assets = 1
        fresh_db.session.add(
            GenericAsset(
                name="Over limit",
                account_id=account_ids[1],
                generic_asset_type_id=asset_type_id,
            )
        )
        with pytest.raises(PlanQuotaExceeded, match="at most 1 asset"):
            fresh_db.session.flush()
        fresh_db.session.rollback()

        # Assigning a limited plan in the same flush must also take the lock.
        no_plan.plan = Plan(name="No assets", max_assets=0)
        fresh_db.session.add(
            GenericAsset(
                name="Forbidden asset",
                account_id=account_ids[0],
                generic_asset_type_id=asset_type_id,
            )
        )
        with pytest.raises(PlanQuotaExceeded, match="at most 0 assets"):
            fresh_db.session.flush()
        fresh_db.session.rollback()

        # Callers can use ordinary dictionaries: missing resources and removals
        # represent zero and must not raise KeyError when a quota is checked.
        _enforce_existing_account_quotas(
            fresh_db.session, {(account_ids[2], "assets"): 1}, {}
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture_lock)


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
        active=True,
        fs_uniquifier="initial-test-user",
        account=account,
    )
    fresh_db.session.add_all([account, user])

    with pytest.raises(PlanQuotaExceeded, match="at most 0 active users"):
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
    assert "at most 3 active users" in response.json["message"]
    assert "Deactivate another user" in response.json["message"]
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
def test_deactivation_frees_seat_and_reactivation_requires_one(
    fresh_db,
    client,
    setup_roles_users_fresh_db,
    setup_accounts_fresh_db,
    requesting_user,
):
    account = setup_accounts_fresh_db["Prosumer"]
    _assign_plan(fresh_db, account, max_users=3)
    colleague = find_user_by_email("test_prosumer_user@seita.nl")
    colleague_id = colleague.id

    response = client.patch(
        url_for("UserAPI:patch", id=colleague_id), json={"active": False}
    )
    assert response.status_code == 200, response.json
    response = client.post(
        url_for("UserAPI:post"),
        json={
            "email": "replacement@example.com",
            "username": "replacement",
            "account_id": account.id,
        },
    )
    assert response.status_code == 201, response.json
    replacement_id = find_user_by_email("replacement@example.com").id

    response = client.patch(
        url_for("UserAPI:patch", id=colleague_id), json={"active": True}
    )
    assert response.status_code == 422, response.json
    assert "at most 3 active users" in response.json["message"]
    fresh_db.session.rollback()
    assert fresh_db.session.get(User, colleague_id).active is False

    response = client.patch(
        url_for("UserAPI:patch", id=replacement_id), json={"active": False}
    )
    assert response.status_code == 200, response.json
    response = client.patch(
        url_for("UserAPI:patch", id=colleague_id), json={"active": True}
    )
    assert response.status_code == 200, response.json
    assert fresh_db.session.get(User, colleague_id).active is True


def test_swapping_active_users_in_one_flush(
    fresh_db, setup_roles_users_fresh_db, setup_accounts_fresh_db
):
    account = setup_accounts_fresh_db["Prosumer"]
    existing = find_user_by_email("test_prosumer_user@seita.nl")
    inactive = User(
        email="inactive@example.com",
        username="inactive",
        password="test",
        fs_uniquifier="inactive-quota-test",
        active=False,
        account=account,
    )
    fresh_db.session.add(inactive)
    fresh_db.session.commit()
    _assign_plan(fresh_db, account, max_users=3)
    existing.active = False
    inactive.active = True
    fresh_db.session.commit()
    assert existing.active is False
    assert inactive.active is True


def test_inactive_users_do_not_consume_seats_when_created_or_transferred(
    fresh_db, setup_roles_users_fresh_db, setup_accounts_fresh_db
):
    account = setup_accounts_fresh_db["Prosumer"]
    _assign_plan(fresh_db, account, max_users=3)
    inactive = User(
        email="inactive@example.com",
        username="inactive",
        password="test",
        fs_uniquifier="inactive-quota-test",
        active=False,
        account=account,
    )
    unset = User(
        email="unset@example.com",
        username="unset",
        password="test",
        fs_uniquifier="unset-quota-test",
        account=account,
    )
    fresh_db.session.add_all([inactive, unset])
    fresh_db.session.commit()
    inactive.account = setup_accounts_fresh_db["Supplier"]
    fresh_db.session.commit()
    inactive.account = account
    fresh_db.session.commit()
    with pytest.raises(PlanQuotaExceeded, match="at most 3 active users"):
        inactive.active = True
        fresh_db.session.flush()
    fresh_db.session.rollback()
    inactive.account = setup_accounts_fresh_db["Supplier"]
    fresh_db.session.commit()
    colleague = find_user_by_email("test_prosumer_user@seita.nl")
    # Expired values must not prevent a same-flush seat swap.
    fresh_db.session.expire(inactive, ["active", "account_id", "account"])
    colleague.active = False
    inactive.account = account
    inactive.active = True
    fresh_db.session.commit()
    assert inactive.account_id == account.id
    assert inactive.active is True


def test_concurrent_reactivations_share_one_remaining_seat(
    fresh_db, setup_roles_users_fresh_db, setup_accounts_fresh_db
):
    account = setup_accounts_fresh_db["Prosumer"]
    users = [
        User(
            email=f"inactive-{i}@example.com",
            username=f"inactive-{i}",
            password="test",
            fs_uniquifier=f"inactive-concurrent-{i}",
            active=False,
            account=account,
        )
        for i in range(2)
    ]
    fresh_db.session.add_all(users)
    find_user_by_email("test_prosumer_user@seita.nl").active = False
    fresh_db.session.commit()
    _assign_plan(fresh_db, account, max_users=3)
    user_ids = [user.id for user in users]
    account_id = account.id
    engine = fresh_db.engine
    barrier = Barrier(2)

    def activate(user_id):
        with Session(engine) as session:
            user = session.get(User, user_id)
            user.active = True
            barrier.wait(timeout=10)
            try:
                session.commit()
                return "activated"
            except PlanQuotaExceeded:
                session.rollback()
                return "quota"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(activate, user_ids))
    assert sorted(outcomes) == ["activated", "quota"]
    fresh_db.session.expire_all()
    assert (
        fresh_db.session.scalar(
            select(func.count(User.id)).where(
                User.account_id == account_id, User.active.is_(True)
            )
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
    with pytest.raises(PlanQuotaExceeded, match="at most 3 assets"):
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
    with pytest.raises(PlanQuotaExceeded, match="at most 1 asset"):
        fresh_db.session.flush()
    fresh_db.session.rollback()

    supplier_user = find_user_by_email("test_supplier_user_4@seita.nl")
    supplier_user.account = prosumer
    with pytest.raises(PlanQuotaExceeded, match="at most 3 active users"):
        fresh_db.session.flush()
    fresh_db.session.rollback()

    client_account = setup_accounts_fresh_db["ConsultancyClient"]
    client_account.consultancy_account = prosumer
    with pytest.raises(PlanQuotaExceeded, match="at most 0 client organisations"):
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

    with pytest.raises(PlanQuotaExceeded, match="consultancy privileges"):
        fresh_db.session.flush()


def test_existing_consultant_cannot_move_to_zero_client_plan(
    fresh_db, setup_roles_users_fresh_db, setup_accounts_fresh_db
):
    prosumer = setup_accounts_fresh_db["Prosumer"]
    _assign_plan(fresh_db, prosumer, max_users=4, max_clients=0)
    consultant = find_user_by_email("test_consultant@seita.nl")
    consultant.account_id = prosumer.id

    with pytest.raises(PlanQuotaExceeded, match="consultancy privileges"):
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
    with pytest.raises(PlanQuotaExceeded, match="at most 1 asset"):
        fresh_db.session.flush()
