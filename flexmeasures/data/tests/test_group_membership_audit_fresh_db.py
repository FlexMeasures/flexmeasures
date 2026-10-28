"""A device group's asset notes in its audit log which devices join and leave it, whichever way the change is made."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from flexmeasures.data.models.audit_log import AssetAuditLog
from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.data.models.user import Account


def events_on(db, asset: GenericAsset) -> list[str]:
    return list(
        db.session.scalars(
            select(AssetAuditLog.event)
            .filter_by(affected_asset_id=asset.id)
            .order_by(AssetAuditLog.id)
        )
    )


def membership_events_on(db, asset: GenericAsset) -> list[str]:
    return [event for event in events_on(db, asset) if "group" in event.lower()]


@pytest.fixture
def streets(fresh_db):
    """Two sites, each with a street that groups devices, and a house on the first."""
    db = fresh_db
    site_type = GenericAssetType(name="site")
    db.session.add(site_type)
    north = GenericAsset(name="North", generic_asset_type=site_type)
    south = GenericAsset(name="South", generic_asset_type=site_type)
    db.session.add_all([north, south])
    db.session.flush()
    north_street = GenericAsset(
        name="North street", generic_asset_type=site_type, parent_asset=north
    )
    south_street = GenericAsset(
        name="South street", generic_asset_type=site_type, parent_asset=south
    )
    house = GenericAsset(name="House", generic_asset_type=site_type, parent_asset=north)
    db.session.add_all([north_street, south_street, house])
    db.session.commit()
    return dict(
        type=site_type,
        north=north,
        south=south,
        north_street=north_street,
        south_street=south_street,
        house=house,
    )


def add_pv(db, streets, group: dict | None, parent: GenericAsset | None = None):
    pv = GenericAsset(
        name="PV",
        generic_asset_type=streets["type"],
        parent_asset=parent or streets["house"],
        flex_model={"group": group} if group else {},
    )
    db.session.add(pv)
    db.session.commit()
    return pv


def test_a_new_member_is_noted_on_its_group(fresh_db, streets):
    street = streets["north_street"]
    pv = add_pv(fresh_db, streets, {"asset": street.id})

    assert membership_events_on(fresh_db, street) == [
        f"Asset 'PV' ({pv.id}) joined group asset 'North street' ({street.id})."
    ]


def test_switching_groups_is_noted_on_both(fresh_db, streets):
    north, south = streets["north_street"], streets["south_street"]
    pv = add_pv(fresh_db, streets, {"asset": north.id})

    pv.flex_model = {"group": {"asset": south.id}}
    fresh_db.session.commit()

    assert membership_events_on(fresh_db, north)[-1] == (
        f"Asset 'PV' ({pv.id}) left group asset 'North street' ({north.id})."
    )
    assert membership_events_on(fresh_db, south) == [
        f"Asset 'PV' ({pv.id}) joined group asset 'South street' ({south.id})."
    ]


def test_a_change_made_in_place_is_noted(fresh_db, streets):
    """A flex-model edited in place, rather than replaced, still counts."""
    street = streets["north_street"]
    pv = add_pv(fresh_db, streets, None)

    pv.flex_model["group"] = {"asset": street.id}
    fresh_db.session.commit()

    assert len(membership_events_on(fresh_db, street)) == 1


def test_an_unrelated_edit_notes_nothing(fresh_db, streets):
    street = streets["north_street"]
    pv = add_pv(fresh_db, streets, {"asset": street.id})

    pv.flex_model = {"group": {"asset": street.id}, "power-capacity": "5 kW"}
    pv.name = "Roof PV"
    fresh_db.session.commit()

    assert len(membership_events_on(fresh_db, street)) == 1


def test_a_deleted_member_is_noted_on_its_group(fresh_db, streets):
    street = streets["north_street"]
    pv = add_pv(fresh_db, streets, {"asset": street.id})
    pv_id = pv.id

    fresh_db.session.delete(pv)
    fresh_db.session.commit()

    assert membership_events_on(fresh_db, street)[-1] == (
        f"Asset 'PV' ({pv_id}) left group asset 'North street' ({street.id}) (the asset was deleted)."
    )


def test_a_deleted_group_is_noted_on_its_members(fresh_db, streets):
    """The members keep naming a group that is gone, so they are the ones to hear about it."""
    street = streets["north_street"]
    street_id = street.id
    pv = add_pv(fresh_db, streets, {"asset": street.id})

    fresh_db.session.delete(street)
    fresh_db.session.commit()

    assert membership_events_on(fresh_db, pv) == [
        f"Group asset 'North street' ({street_id}), named in the flex-model of this asset, was deleted."
    ]


@pytest.mark.parametrize(
    "group",
    [{"asset": "abc"}, {"asset": [1, 2]}, {"asset": 10**20}, {"sensor": "abc"}],
)
def test_a_malformed_group_does_not_fail_the_flush(fresh_db, streets, group):
    """The API validates a group, but a script may write anything, and the listener runs on every flush."""
    add_pv(fresh_db, streets, group)

    assert membership_events_on(fresh_db, streets["north_street"]) == []


def test_a_change_from_a_failed_flush_is_not_noted_later(fresh_db, streets):
    """The flush that would have added the member fails, so its group should not hear of it with the next flush."""
    street = streets["north_street"]
    duplicate = GenericAsset(
        name="House",  # the north site already has a child called House
        generic_asset_type=streets["type"],
        parent_asset=streets["north"],
        flex_model={"group": {"asset": street.id}},
    )
    fresh_db.session.add(duplicate)
    with pytest.raises(IntegrityError):
        fresh_db.session.flush()
    fresh_db.session.rollback()

    streets["south"].name = "South side"
    fresh_db.session.commit()

    assert membership_events_on(fresh_db, street) == []


def test_a_group_in_another_organisation_hears_nothing(fresh_db, streets):
    """A device may name any existing asset as its group, but not write in the audit log of another organisation."""
    mine, other = Account(name="My organisation"), Account(name="Other organisation")
    fresh_db.session.add_all([mine, other])
    fresh_db.session.flush()
    street = streets["south_street"]
    street.account_id = other.id
    fresh_db.session.commit()

    pv = GenericAsset(
        name="PV",
        generic_asset_type=streets["type"],
        owner=mine,
        flex_model={"group": {"asset": street.id}},
    )
    fresh_db.session.add(pv)
    fresh_db.session.commit()

    assert membership_events_on(fresh_db, street) == []


def test_a_member_moved_to_another_site_is_noted(fresh_db, streets):
    """A scheduler finds members only on the site it schedules, so moving a member to another site takes it out of its group."""
    street = streets["north_street"]
    pv = add_pv(fresh_db, streets, {"asset": street.id})

    pv.parent_asset = streets["south"]
    fresh_db.session.commit()

    north, south = streets["north"], streets["south"]
    assert membership_events_on(fresh_db, street)[-1] == (
        f"Asset 'PV' ({pv.id}), a member of group asset 'North street' ({street.id}),"
        f" moved from site 'North' ({north.id}) to site 'South' ({south.id})."
    )


def test_a_member_moved_with_its_parent_is_noted(fresh_db, streets):
    """Moving a house moves its devices too."""
    street, house = streets["north_street"], streets["house"]
    pv = add_pv(fresh_db, streets, {"asset": street.id})

    house.parent_asset_id = streets["south"].id
    fresh_db.session.commit()

    assert f"Asset 'PV' ({pv.id}), a member of group" in (
        membership_events_on(fresh_db, street)[-1]
    )


def test_a_move_within_the_site_notes_nothing(fresh_db, streets):
    street = streets["north_street"]
    add_pv(fresh_db, streets, {"asset": street.id})

    streets["house"].parent_asset = street
    fresh_db.session.commit()

    assert len(membership_events_on(fresh_db, street)) == 1


def test_a_group_moved_along_with_its_members_notes_nothing(fresh_db, streets):
    """The group and its member end up on the same site again, so the membership holds."""
    house = streets["house"]
    add_pv(fresh_db, streets, {"asset": house.id})

    house.parent_asset = streets["south"]
    fresh_db.session.commit()

    assert len(membership_events_on(fresh_db, house)) == 1


def test_a_sensor_referenced_group_is_noted_on_the_sensor_asset(fresh_db, streets):
    street = streets["north_street"]
    street_power = Sensor(
        "street power",
        generic_asset=street,
        unit="kW",
        event_resolution=timedelta(minutes=15),
    )
    fresh_db.session.add(street_power)
    fresh_db.session.commit()

    pv = add_pv(fresh_db, streets, {"sensor": street_power.id})

    assert membership_events_on(fresh_db, street) == [
        f"Asset 'PV' ({pv.id}) joined group sensor 'street power' ({street_power.id})."
    ]
