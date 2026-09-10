import json

from flask import url_for
import pytest
from sqlalchemy import select

from flexmeasures.data.models.audit_log import AuditLog
from flexmeasures.data.models.user import Account
from flexmeasures.data.services.users import find_user_by_email

pytestmark = pytest.mark.parametrize(
    "requesting_user", ["test_admin_user@seita.nl"], indirect=True
)


def account_events(db, account_id):
    return db.session.scalars(
        select(AuditLog).filter_by(affected_account_id=account_id)
    ).all()


@pytest.mark.parametrize("resubmit_unchanged_fields", [False, True])
def test_account_attribute_audit_reports_only_changes(
    fresh_db,
    client,
    setup_roles_users_fresh_db,
    requesting_user,
    resubmit_unchanged_fields,
):
    """Attribute edits record old and new values without listing unchanged fields."""
    account = find_user_by_email("test_prosumer_user@seita.nl").account
    account.attributes = {"max_power_kw": 10}
    fresh_db.session.commit()
    previous_ids = {log.id for log in account_events(fresh_db, account.id)}
    payload = {"attributes": json.dumps({"max_power_kw": 50})}
    if resubmit_unchanged_fields:
        payload.update(
            name=account.name,
            logo_url=account.logo_url,
            account_roles=[role.id for role in account.account_roles],
        )

    response = client.patch(url_for("AccountAPI:patch", id=account.id), json=payload)

    assert response.status_code == 200, response.json
    logs = [
        log
        for log in account_events(fresh_db, account.id)
        if log.id not in previous_ids
    ]
    assert len(logs) == 1
    event = logs[0].event
    assert "attributes" in event
    assert "max_power_kw" in event
    assert "10" in event and "50" in event
    for unchanged_field in ("name", "logo_url", "account_roles", "plan_id"):
        assert unchanged_field not in event
    assert logs[0].active_user_id == requesting_user.id


@pytest.mark.parametrize("payload_type", ["empty", "same", "reordered_roles"])
def test_account_noop_patch_does_not_add_audit_log(
    fresh_db, client, setup_roles_users_fresh_db, requesting_user, payload_type
):
    """Unchanged values and reordered role lists produce no audit entry."""
    account = fresh_db.session.execute(
        select(Account).filter_by(name="Multi Role Account")
    ).scalar_one()
    payload = {}
    if payload_type == "same":
        payload = {"name": account.name, "attributes": json.dumps(account.attributes)}
    elif payload_type == "reordered_roles":
        payload = {
            "account_roles": [role.id for role in reversed(account.account_roles)]
        }
    previous_ids = {log.id for log in account_events(fresh_db, account.id)}

    response = client.patch(url_for("AccountAPI:patch", id=account.id), json=payload)

    assert response.status_code == 200, response.json
    assert {log.id for log in account_events(fresh_db, account.id)} == previous_ids


def test_account_large_attribute_audit_fits_storage(
    fresh_db, client, setup_roles_users_fresh_db, requesting_user
):
    """Large attribute values can be saved with bounded audit events."""
    account = find_user_by_email("test_prosumer_user@seita.nl").account
    account.attributes = {"description": "before" * 200}
    fresh_db.session.commit()
    previous_ids = {log.id for log in account_events(fresh_db, account.id)}
    attributes = {"description": "after" * 200}

    response = client.patch(
        url_for("AccountAPI:patch", id=account.id),
        json={"attributes": json.dumps(attributes)},
    )

    assert response.status_code == 200, response.json
    assert json.loads(response.json["attributes"]) == attributes
    logs = [
        log
        for log in account_events(fresh_db, account.id)
        if log.id not in previous_ids
    ]
    assert len(logs) == 1
    assert len(logs[0].event) <= 500
    assert "attributes" in logs[0].event
    assert "before" in logs[0].event and "after" in logs[0].event


def test_account_role_audit_uses_role_names(
    fresh_db, client, setup_roles_users_fresh_db, requesting_user
):
    """Role edits display meaningful old and new role names."""
    account = fresh_db.session.execute(
        select(Account).filter_by(name="Multi Role Account")
    ).scalar_one()
    remaining_role = next(
        role for role in account.account_roles if role.name == "Prosumer"
    )
    previous_ids = {log.id for log in account_events(fresh_db, account.id)}

    response = client.patch(
        url_for("AccountAPI:patch", id=account.id),
        json={"account_roles": [remaining_role.id]},
    )

    assert response.status_code == 200, response.json
    logs = [
        log
        for log in account_events(fresh_db, account.id)
        if log.id not in previous_ids
    ]
    assert len(logs) == 1
    assert "account_roles" in logs[0].event
    for role_name in ("Prosumer", "Supplier", "Dummy"):
        assert role_name in logs[0].event
    assert "object at" not in logs[0].event
