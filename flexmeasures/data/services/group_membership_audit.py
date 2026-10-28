"""Note in the audit log of a device group when its membership changes.

A device joins a group through the `group` field of its own flex-model, so the group's asset is never edited when a device joins or leaves it.
Without these entries, the history of a group's membership could only be pieced together from the audit logs of every asset that ever named it.

The changes are picked up from the session, so they are noted whichever way an asset was created, edited, moved or deleted:
through the API, the UI, the CLI or a script.
An asset deleted with one `delete` statement, as `delete_asset` does, never passes through the session, and neither do its offspring and their sensors,
so `delete_asset` notes those changes itself, with `note_deletion`.

A report automation over a group may narrow it down to members of one asset type.
Changing a member's type then moves it in or out of what the report aggregates, which is noted on the group's asset too,
and creating such an automation notes which members it starts out with.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import Session

from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor

#: Key under which the changes found before a flush wait in `Session.info` until the flush has assigned IDs.
_PENDING_KEY = "group_membership_changes"


@dataclass
class _Change:
    """One change to the membership of one group, to be noted on the group's asset (or, for a deleted group, on the member's).

    The group is described before the flush, while a group that is being deleted can still be looked up,
    and the member after it, once a new member has its ID.
    """

    member: GenericAsset
    group_asset: GenericAsset | None
    group_label: str
    what: str  # "joined", "left", "moved", "group deleted" or "report"
    detail: str = ""


def _group_key(flex_model: dict | None) -> tuple[str, int] | None:
    from flexmeasures.data.models.planning.devices import resolve_group_key

    try:
        key = resolve_group_key(flex_model or {})
    except (TypeError, ValueError, AttributeError):
        # a malformed reference names no group we could note anything on
        return None
    # an ID that is no integer the database can hold names no group either, and looking it up would fail the flush
    if key is None or type(key[1]) is not int or not 0 < key[1] < 2**31:
        return None
    return key


def _site_of(asset: GenericAsset | None) -> GenericAsset | None:
    """Return the top-level asset above (or at) the given asset."""
    while asset is not None and asset.parent_asset is not None:
        asset = asset.parent_asset
    return asset


def _label_asset(asset: GenericAsset | None) -> str:
    if asset is None:
        return "no site"
    return f"'{asset.name}' ({asset.id})"


def _stored_state(session: Session, asset_ids: list[int]) -> dict[int, tuple]:
    """Return the flex-model, parent and type of each asset as the database holds them, from before this flush."""
    if not asset_ids:
        return {}
    with session.no_autoflush:
        rows = session.execute(
            sa.select(
                GenericAsset.id,
                GenericAsset.flex_model,
                GenericAsset.parent_asset_id,
                GenericAsset.generic_asset_type_id,
            ).where(GenericAsset.id.in_(asset_ids))
        ).all()
    return {
        row.id: (row.flex_model, row.parent_asset_id, row.generic_asset_type_id)
        for row in rows
    }


def _members_naming(session: Session, kind: str, ids: list[int]) -> list[GenericAsset]:
    """Return the assets whose flex-model names one of the given assets or sensors as its group."""
    if not ids:
        return []
    reference = GenericAsset.flex_model["group"][kind].astext
    with session.no_autoflush:
        return list(
            session.scalars(
                sa.select(GenericAsset).where(reference.in_([str(i) for i in ids]))
            )
        )


def _find_changes(session: Session, flush_context, instances) -> None:
    """Work out, before the flush, which group memberships it changes."""
    # changes found before a flush that failed were never made, so they are dropped rather than noted with the next flush
    session.info.pop(_PENDING_KEY, None)
    new = [obj for obj in session.new if isinstance(obj, GenericAsset)]
    dirty = [
        obj
        for obj in session.dirty
        if isinstance(obj, GenericAsset) and session.is_modified(obj)
    ]
    deleted_assets = [obj for obj in session.deleted if isinstance(obj, GenericAsset)]
    deleted_sensors = [obj for obj in session.deleted if isinstance(obj, Sensor)]
    if not (new or dirty or deleted_assets or deleted_sensors):
        return

    changes: list[_Change] = []
    deleted_ids = {obj.id for obj in deleted_assets}

    for asset in new:
        key = _group_key(asset.flex_model)
        if key is not None:
            changes.append(_change(session, asset, key, "joined"))

    stored = _stored_state(session, [obj.id for obj in dirty + deleted_assets])
    for asset in dirty:
        changes.extend(
            _edits(session, asset, *stored.get(asset.id, (None, None, None)))
        )
    changes.extend(_deletions(session, deleted_assets, deleted_sensors, stored))

    changes = _worth_noting(changes, deleted_ids)
    if changes:
        session.info.setdefault(_PENDING_KEY, []).extend(changes)


def _worth_noting(changes: list[_Change], deleted_ids: set[int]) -> list[_Change]:
    """Leave out the changes of a group that goes away along with its member, and of a group in another organisation.

    A `group` reference is only checked to exist, so a device may name an asset of another organisation as its group.
    No scheduler or report finds it there, since a group's members sit on the group's site,
    and the device's organisation should not get to write in the audit log of the other one.
    """
    return [
        change
        for change in changes
        if (
            change.what == "group deleted"
            or (
                change.group_asset is not None
                and change.group_asset.id not in deleted_ids
            )
        )
        and (
            change.group_asset is None
            or _account_id(change.group_asset) == _account_id(change.member)
        )
    ]


def _account_id(asset: GenericAsset) -> int | None:
    """Return the ID of the asset's organisation, also when a new asset was given its owner rather than its owner's ID."""
    owner = asset.owner
    return owner.id if owner is not None else asset.account_id


def note_deletion(asset: GenericAsset) -> None:
    """Note the membership changes of deleting the given asset in one statement, which no flush gets to see.

    Deleting an asset that way, as `delete_asset` does, also deletes its offspring and their sensors through the database,
    so none of them passes through `Session.deleted`.
    Call this right before that statement, while they can all still be looked up.
    """
    from flexmeasures.data import db

    session = db.session
    assets = [asset, *asset.offspring]
    sensors = [sensor for each in assets for sensor in each.sensors]
    stored = _stored_state(session, [each.id for each in assets])
    changes = _deletions(session, assets, sensors, stored)
    for change in _worth_noting(changes, {each.id for each in assets}):
        _write(change)


def _edits(
    session: Session,
    asset: GenericAsset,
    old_flex_model: dict | None,
    old_parent_id: int | None,
    old_type_id: int | None,
) -> list[_Change]:
    """Note an edited asset leaving or joining a group, a member moving to another site, and a member changing type."""
    changes = []
    old_key, new_key = _group_key(old_flex_model), _group_key(asset.flex_model)
    if old_key != new_key:
        if old_key is not None:
            changes.append(_change(session, asset, old_key, "left"))
        if new_key is not None:
            changes.append(_change(session, asset, new_key, "joined"))
    new_parent_id = _new_parent_id(asset)
    if old_parent_id != new_parent_id:
        changes.extend(_moves(session, asset, old_parent_id, new_parent_id))
    new_type_id = _new_type_id(asset)
    # a device that changes group as well is noted leaving one group and joining the other, and was in no report of its new group before
    if old_type_id is not None and old_type_id != new_type_id and old_key == new_key:
        changes.extend(_type_changes(session, asset, old_type_id, new_type_id))
    return changes


def _deletions(
    session: Session,
    deleted_assets: list[GenericAsset],
    deleted_sensors: list[Sensor],
    stored: dict[int, tuple],
) -> list[_Change]:
    """Note deleted members leaving their group, and members whose group is deleted."""
    changes = []
    deleted_ids = {obj.id for obj in deleted_assets}
    for asset in deleted_assets:
        old_flex_model = stored.get(asset.id, (asset.flex_model,))[0]
        key = _group_key(old_flex_model)
        if key is not None:
            changes.append(
                _change(session, asset, key, "left", " (the asset was deleted)")
            )

    # members whose group goes away keep naming it, so note on them that it is gone
    for kind, ids in (
        ("asset", [obj.id for obj in deleted_assets]),
        ("sensor", [obj.id for obj in deleted_sensors]),
    ):
        for member in _members_naming(session, kind, ids):
            key = _group_key(member.flex_model)
            if member.id not in deleted_ids and key is not None:
                changes.append(_change(session, member, key, "group deleted"))
    return changes


def _change(
    session: Session,
    member: GenericAsset,
    key: tuple[str, int],
    what: str,
    detail: str = "",
) -> _Change:
    return _Change(
        member, _group_asset(session, key), _group_label(session, key), what, detail
    )


def _new_parent_id(asset: GenericAsset) -> int | None:
    """Return the ID of the parent the asset is about to have, whether its parent or its parent's ID was set."""
    state = sa.inspect(asset)
    if state.attrs.parent_asset.history.has_changes():
        parent = asset.parent_asset
        return parent.id if parent is not None else None
    return asset.parent_asset_id


def _new_type_id(asset: GenericAsset) -> int | None:
    """Return the ID of the type the asset is about to have, whether its type or its type's ID was set."""
    state = sa.inspect(asset)
    if state.attrs.generic_asset_type.history.has_changes():
        asset_type = asset.generic_asset_type
        return asset_type.id if asset_type is not None else None
    return asset.generic_asset_type_id


def _type_changes(
    session: Session,
    asset: GenericAsset,
    old_type_id: int,
    new_type_id: int | None,
) -> list[_Change]:
    """Note a member whose new type takes it into, or out of, a report automation that aggregates only one type of its group's members."""
    from flexmeasures.data.models.generic_assets import GenericAssetType

    if _members_naming(session, "asset", [asset.id]):
        # a group entry is no member device itself; the type filter applies to the devices behind it
        return []
    old_type = session.get(GenericAssetType, old_type_id)
    new_type = (
        session.get(GenericAssetType, new_type_id) if new_type_id is not None else None
    )
    old_name = old_type.name if old_type is not None else None
    new_name = new_type.name if new_type is not None else None

    changes = []
    for automation, key, asset_type in _filtered_group_reports(
        session, _group_chain(session, asset)
    ):
        was_selected, is_selected = old_name == asset_type, new_name == asset_type
        if was_selected == is_selected:
            continue
        verb = "entered" if is_selected else "left"
        detail = (
            f" {verb} the members of group {_group_label(session, key)}"
            f" that report automation '{automation.name}' ({automation.id}) aggregates,"
            f" filtered to asset type '{asset_type}', as its type changed from '{old_name}' to '{new_name}'"
        )
        changes.append(_change(session, asset, key, "report", detail))
    return changes


def _group_chain(session: Session, asset: GenericAsset) -> list[tuple[str, int]]:
    """Return the groups the asset belongs to: its own group, the group that group belongs to, and so on."""
    chain: list[tuple[str, int]] = []
    key = _group_key(asset.flex_model)
    while key is not None and key not in chain:
        chain.append(key)
        entry = _group_entry_asset(session, key)
        key = _group_key(entry.flex_model) if entry is not None else None
    return chain


def _group_entry_asset(session: Session, key: tuple[str, int]) -> GenericAsset | None:
    """Return the asset whose flex-model entry defines the group, which says which group it belongs to in turn."""
    kind, group_id = key
    if kind == "asset":
        return session.get(GenericAsset, group_id)
    with session.no_autoflush:
        return session.scalars(
            sa.select(GenericAsset)
            .where(GenericAsset.flex_model["sensor"].astext == str(group_id))
            .limit(1)
        ).first()


def _filtered_group_reports(session: Session, chain: list[tuple[str, int]]):
    """Yield each report automation over one of the given groups that aggregates only one asset type, with its group and that type."""
    from flexmeasures.data.models.automations import Automation
    from flexmeasures.data.models.planning.devices import resolve_group_reference

    if not chain:
        return
    with session.no_autoflush:
        automations = session.scalars(
            sa.select(Automation).where(Automation.type == "reporting")
        ).all()
    for automation in automations:
        config = _generator_config(automation)
        asset_type = (config.get("members") or {}).get("asset-type")
        key = resolve_group_reference(config.get("group"))
        if asset_type and key in chain:
            yield automation, key, asset_type


def _generator_config(automation) -> dict:
    generator = automation.generator
    attributes = (generator.attributes if generator is not None else None) or {}
    return (attributes.get("data_generator") or {}).get("config") or {}


def note_report_selection(automation, reporter) -> None:
    """Note on a group's asset which of its members a new report automation aggregates, when it aggregates only one asset type.

    The later notes on members entering or leaving the selection then have a starting point.
    """
    from flexmeasures.data import db
    from flexmeasures.data.models.audit_log import AssetAuditLog
    from flexmeasures.data.models.planning.devices import resolve_group_reference

    config = _generator_config(automation)
    asset_type = (config.get("members") or {}).get("asset-type")
    key = resolve_group_reference(config.get("group"))
    if not asset_type or key is None:
        return
    session = db.session
    group_asset = _group_asset(session, key)
    if group_asset is None:
        return
    members = {
        sensor.generic_asset.id: sensor.generic_asset
        for sensor in reporter.input_sensors
    }
    listed = ", ".join(_label_asset(members[i]) for i in sorted(members)) or "none"
    AssetAuditLog.add_record(
        group_asset,
        f"Report automation '{automation.name}' ({automation.id}) aggregates the members of group {_group_label(session, key)}"
        f" of asset type '{asset_type}', starting with: {listed}.",
    )


def _moves(
    session: Session,
    asset: GenericAsset,
    old_parent_id: int | None,
    new_parent_id: int | None,
) -> list[_Change]:
    """Note the members in a moved subtree that end up on another site than before.

    A scheduler only finds the members on the site it schedules, so such a member drops out of (or comes into) its group,
    unless the group's own asset moved along with it.
    """
    old_parent = (
        session.get(GenericAsset, old_parent_id) if old_parent_id is not None else None
    )
    new_parent = (
        session.get(GenericAsset, new_parent_id) if new_parent_id is not None else None
    )
    old_site = _site_of(old_parent) or asset
    new_site = _site_of(new_parent) or asset
    if old_site is new_site:
        return []
    subtree = [asset, *asset.offspring]
    moved_ids = {a.id for a in subtree}
    detail = f" from site {_label_asset(old_site)} to site {_label_asset(new_site)}"
    changes = []
    for member in subtree:
        key = _group_key(member.flex_model)
        if key is None:
            continue
        group_asset = _group_asset(session, key)
        if group_asset is not None and group_asset.id in moved_ids:
            continue
        changes.append(_change(session, member, key, "moved", detail))
    return changes


def _group_asset(session: Session, key: tuple[str, int]) -> GenericAsset | None:
    """Return the asset whose audit log the group's changes belong in."""
    kind, group_id = key
    if kind == "asset":
        return session.get(GenericAsset, group_id)
    sensor = session.get(Sensor, group_id)
    return sensor.generic_asset if sensor is not None else None


def _group_label(session: Session, key: tuple[str, int]) -> str:
    kind, group_id = key
    model = GenericAsset if kind == "asset" else Sensor
    obj = session.get(model, group_id)
    name = f"'{obj.name}' " if obj is not None else ""
    return f"{kind} {name}({group_id})"


def _note_changes(session: Session, flush_context) -> None:
    """Write the audit log entries for the changes found before the flush, now that every asset has an ID."""
    changes: list[_Change] = session.info.pop(_PENDING_KEY, [])
    for change in changes:
        _write(change)


def _write(change: _Change) -> None:
    """Write the audit log entry for one change."""
    from flexmeasures.data.models.audit_log import AssetAuditLog

    member = f"Asset {_label_asset(change.member)}"
    group = change.group_label
    if change.what == "group deleted":
        AssetAuditLog.add_record(
            change.member,
            f"Group {group}, named in the flex-model of this asset, was deleted.",
        )
    elif change.what == "report":
        AssetAuditLog.add_record(change.group_asset, f"{member}{change.detail}.")
    elif change.what == "moved":
        AssetAuditLog.add_record(
            change.group_asset,
            f"{member}, a member of group {group}, moved{change.detail}.",
        )
    else:
        AssetAuditLog.add_record(
            change.group_asset,
            f"{member} {change.what} group {group}{change.detail}.",
        )


def register(session) -> None:
    """Note group membership changes on every flush of the given session (or session factory)."""
    if not event.contains(session, "before_flush", _find_changes):
        event.listen(session, "before_flush", _find_changes)
        event.listen(session, "after_flush_postexec", _note_changes)
