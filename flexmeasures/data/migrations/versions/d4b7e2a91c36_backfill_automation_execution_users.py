"""Backfill the user each automation runs as, from the asset audit log.

Automations made through the API before b63a02d5e184 (and copies made before copies kept the copying user)
have no execution user, which also means "made through the CLI", so their runs are not checked against
anyone's permissions. The asset audit log says who made most of them:

- An automation's own "Created automation '<name>' (<id>) via …" record names the user who made it.
  A record without a user was made through the CLI, and the automation keeps no execution user.
- An automation copied along with an asset has no record of its own. The copy's root asset has a
  "Copied asset '<name>': <id> to '<name>': <copy id>" record, which names the user who copied it.
- An automation for which neither is found keeps no execution user.

A record whose user has since been deleted still names the user, but no longer their id.
Such an automation gets execution user 0, which belongs to no user, so its runs fail
(as for any automation whose user was deleted after this migration), rather than run unchecked.

Revision ID: d4b7e2a91c36
Revises: bf22b21d0990
"""

from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa

revision = "d4b7e2a91c36"
down_revision = "bf22b21d0990"
branch_labels = None
depends_on = None

# The execution user of an automation made by a user who has since been deleted (no user has id 0).
DELETED_USER_ID = 0


def upgrade():
    backfill_execution_users(op.get_bind())


def downgrade():
    # The backfilled users stay: they were already true before this migration, just not recorded.
    pass


def backfill_execution_users(connection) -> dict[int, int]:
    """Set the execution user of automations that have none, where the asset audit log names one.

    :returns: the execution user id set, per automation id
    """
    automations = connection.execute(
        sa.text("SELECT id, asset_id FROM automation WHERE execution_user_id IS NULL")
    ).fetchall()
    backfilled = {}
    for automation_id, asset_id in automations:
        user_id = _creating_user(connection, automation_id, asset_id)
        if user_id is None:
            user_id = _copying_user(connection, asset_id)
        if user_id is not None:
            backfilled[automation_id] = user_id
    for automation_id, user_id in backfilled.items():
        connection.execute(
            sa.text(
                "UPDATE automation SET execution_user_id = :user_id WHERE id = :id"
            ),
            {"user_id": user_id, "id": automation_id},
        )
    return backfilled


def _user_of(record) -> int | None:
    """The user who acted, by id; DELETED_USER_ID for a deleted user; None for the CLI."""
    active_user_id, active_user_name = record
    if active_user_id is not None:
        return active_user_id
    if active_user_name is not None:
        return DELETED_USER_ID
    return None


def _creating_user(connection, automation_id: int, asset_id: int) -> int | None:
    """The user named by the automation's own creation record, if it has one."""
    pattern = re.compile(rf"^Created automation '.*' \({automation_id}\) via ")
    records = connection.execute(
        sa.text(
            "SELECT event, active_user_id, active_user_name FROM asset_audit_log"
            " WHERE affected_asset_id = :asset_id AND event LIKE 'Created automation %'"
            " ORDER BY event_datetime, id"
        ),
        {"asset_id": asset_id},
    ).fetchall()
    for event, active_user_id, active_user_name in records:
        if pattern.match(event):
            return _user_of((active_user_id, active_user_name))
    return None


def _copying_user(connection, asset_id: int) -> int | None:
    """The user who copied the asset, or the copied subtree it is part of.

    Only the root of a copied subtree has a copy record, so this looks up the asset's ancestors,
    stopping at an asset that was created rather than copied.
    """
    visited = set()
    while asset_id is not None and asset_id not in visited:
        visited.add(asset_id)
        records = connection.execute(
            sa.text(
                "SELECT event, active_user_id, active_user_name FROM asset_audit_log"
                " WHERE affected_asset_id = :asset_id"
                " AND (event LIKE 'Copied asset %' OR event LIKE 'Created asset %')"
                " ORDER BY event_datetime, id"
            ),
            {"asset_id": asset_id},
        ).fetchall()
        copied = re.compile(rf"^Copied asset '.*': \d+ to '.*': {asset_id}(\.|$)")
        for event, active_user_id, active_user_name in records:
            if copied.match(event):
                return _user_of((active_user_id, active_user_name))
            if event.startswith("Created asset "):
                return None
        asset_id = connection.execute(
            sa.text("SELECT parent_asset_id FROM generic_asset WHERE id = :asset_id"),
            {"asset_id": asset_id},
        ).scalar()
    return None
