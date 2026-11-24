"""Checks for the data migration that backfills the user each automation runs as, from the asset audit log."""

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

from pytz import utc

from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.automations import Automation
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.user import User


def _migration():
    """Load the migration module by path, as its file name is not an importable module name."""
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "d4b7e2a91c36_backfill_automation_execution_users.py"
    )
    spec = importlib.util.spec_from_file_location("backfill_users_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backfill_automation_execution_users(
    fresh_db, setup_roles_users_fresh_db, setup_generic_asset_types_fresh_db
):
    db = fresh_db
    users = [
        db.session.get(User, user_id) for user_id in setup_roles_users_fresh_db.values()
    ]
    creator, copier, already_set = users[0], users[1], users[2]
    asset_type = setup_generic_asset_types_fresh_db["battery"]
    account_id = creator.account_id
    generator = DataSource(name="forecaster", type="forecaster")
    db.session.add(generator)

    def asset(name: str, parent: GenericAsset | None = None) -> GenericAsset:
        new_asset = GenericAsset(
            name=name,
            generic_asset_type=asset_type,
            account_id=account_id,
            parent_asset_id=parent.id if parent else None,
        )
        db.session.add(new_asset)
        db.session.flush()
        return new_asset

    def automation(name: str, on: GenericAsset, user_id=None) -> Automation:
        new_automation = Automation(
            asset_id=on.id,
            name=name,
            cronstr="0 6 * * *",
            generator=generator,
            execution_user_id=user_id,
        )
        db.session.add(new_automation)
        db.session.flush()
        return new_automation

    def record(on: GenericAsset, event: str, user=None, user_name=None):
        db.session.add(
            AssetAuditLog(
                event_datetime=datetime(2026, 10, 1, tzinfo=utc),
                event=event,
                active_user_id=user.id if user else None,
                active_user_name=user.username if user else user_name,
                affected_asset_id=on.id,
            )
        )

    site = asset("site")
    via_api = automation("via API", site)
    record(site, f"Created automation 'via API' ({via_api.id}) via API.", creator)
    via_cli = automation("via CLI", site)
    record(site, f"Created automation 'via CLI' ({via_cli.id}) via CLI.")
    by_deleted_user = automation("by a deleted user", site)
    record(
        site,
        f"Created automation 'by a deleted user' ({by_deleted_user.id}) via API.",
        user_name="someone who left",
    )
    without_record = automation("without record", site)
    with_user = automation("with user", site, user_id=already_set.id)
    record(site, f"Created automation 'with user' ({with_user.id}) via API.", creator)

    # A copied subtree: only its root has a record, naming the user who copied it.
    copied_root = asset("site (copy)")
    record(
        copied_root,
        f"Copied asset 'site': {site.id} to 'site (copy)': {copied_root.id}."
        " Skipped 1 automation(s), each recorded on its own.",
        copier,
    )
    copied_child = asset("battery", parent=copied_root)
    on_copied_root = automation("copied", copied_root)
    on_copied_child = automation("copied too", copied_child)
    # An asset created under the copy later on is not a copy.
    created_later = asset("added later", parent=copied_root)
    record(created_later, f"Created asset 'added later': {created_later.id}", creator)
    on_created_later = automation("not copied", created_later)
    db.session.flush()

    backfilled = _migration().backfill_execution_users(db.session.connection())
    db.session.expire_all()

    def execution_user(an_automation: Automation) -> int | None:
        return db.session.get(Automation, an_automation.id).execution_user_id

    assert execution_user(via_api) == creator.id
    assert execution_user(via_cli) is None, "null means made through the CLI"
    assert execution_user(by_deleted_user) == 0, "runs fail, rather than go unchecked"
    assert execution_user(without_record) is None
    assert execution_user(with_user) == already_set.id, "a set user is kept"
    assert execution_user(on_copied_root) == copier.id
    assert execution_user(on_copied_child) == copier.id
    assert execution_user(on_created_later) is None
    assert set(backfilled) == {
        via_api.id,
        by_deleted_user.id,
        on_copied_root.id,
        on_copied_child.id,
    }

    # Running it again changes nothing.
    assert _migration().backfill_execution_users(db.session.connection()) == {}
