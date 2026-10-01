"""Checks for the data migration that couples each data source to the organisation it recorded for.

The migration moves beliefs between sources, so its body is exercised here against a real database,
rather than only on the way past in an upgrade.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pytz import utc
from sqlalchemy import select
from timely_beliefs import BeliefsDataFrame  # noqa: F401

from flexmeasures.data.models.data_sources import DataSource, SensorDataSource
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor, TimedBelief


def _migration():
    """Load the migration module by path, as its file name is not an importable module name."""
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "c5e1a7b94d20_couple_data_sources_to_organisations.py"
    )
    spec = importlib.util.spec_from_file_location("couple_sources_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _asset_with_sensor(db, account, asset_type, name: str) -> Sensor:
    asset = GenericAsset(
        name=name,
        generic_asset_type=asset_type,
        account_id=account.id if account else None,
    )
    db.session.add(asset)
    db.session.flush()
    sensor = Sensor(
        name=f"{name} sensor", generic_asset=asset, event_resolution=timedelta(hours=1)
    )
    db.session.add(sensor)
    db.session.flush()
    return sensor


def _record(
    db,
    sensor: Sensor,
    source: DataSource,
    event_start: datetime,
    belief_horizon: timedelta = timedelta(hours=0),
) -> None:
    db.session.add(
        TimedBelief(
            sensor=sensor,
            source=source,
            event_start=event_start,
            belief_horizon=belief_horizon,
            event_value=1.0,
        )
    )
    db.session.add(SensorDataSource(sensor_id=sensor.id, source_id=source.id))
    db.session.flush()


@pytest.fixture
def unowned_forecaster(fresh_db) -> DataSource:
    """A data source as every data generator used to make one: belonging to no organisation."""
    source = DataSource(
        name="Seita",
        type="forecaster",
        model="TrainPredictPipeline",
        version="1",
        attributes={"data_generator": {"config": {"model": "CustomLGBM"}}},
    )
    fresh_db.session.add(source)
    fresh_db.session.flush()
    assert source.account_id is None
    return source


def test_a_source_recording_for_one_organisation_is_coupled_to_it(
    fresh_db,
    setup_accounts_fresh_db,
    setup_generic_asset_types_fresh_db,
    unowned_forecaster,
):
    """The common case: fill the column in place, so that the source keeps the id everything points at."""
    prosumer = setup_accounts_fresh_db["Prosumer"]
    sensor = _asset_with_sensor(
        fresh_db,
        prosumer,
        setup_generic_asset_types_fresh_db["battery"],
        "prosumer site",
    )
    _record(fresh_db, sensor, unowned_forecaster, datetime(2026, 10, 1, tzinfo=utc))
    source_id = unowned_forecaster.id

    _migration().couple_sources_to_organisations(
        fresh_db.session.connection(), splitting=False
    )
    fresh_db.session.expire_all()

    coupled = fresh_db.session.get(DataSource, source_id)
    assert (
        coupled.account_id == prosumer.id
    ), "the source keeps its id and gains the organisation"


def test_a_source_recording_only_on_public_assets_keeps_no_organisation(
    fresh_db,
    setup_accounts_fresh_db,
    setup_generic_asset_types_fresh_db,
    unowned_forecaster,
):
    """A generator that only ever wrote to public assets belongs to no organisation, which is what the host's own sources look like."""
    public_sensor = _asset_with_sensor(
        fresh_db, None, setup_generic_asset_types_fresh_db["battery"], "public site"
    )
    _record(
        fresh_db, public_sensor, unowned_forecaster, datetime(2026, 10, 1, tzinfo=utc)
    )
    public_source_id = unowned_forecaster.id

    # A second source on an owned asset, so that a migration doing nothing at all fails this check rather than passing it.
    owned_source = DataSource(
        name="Seita", type="forecaster", model="OtherPipeline", version="1"
    )
    fresh_db.session.add(owned_source)
    fresh_db.session.flush()
    prosumer = setup_accounts_fresh_db["Prosumer"]
    owned_sensor = _asset_with_sensor(
        fresh_db,
        prosumer,
        setup_generic_asset_types_fresh_db["battery"],
        "prosumer site",
    )
    _record(fresh_db, owned_sensor, owned_source, datetime(2026, 10, 1, tzinfo=utc))
    owned_source_id = owned_source.id

    _migration().couple_sources_to_organisations(
        fresh_db.session.connection(), splitting=False
    )
    fresh_db.session.expire_all()

    assert fresh_db.session.get(DataSource, public_source_id).account_id is None
    assert fresh_db.session.get(DataSource, owned_source_id).account_id == prosumer.id


def test_an_automation_couples_a_source_that_has_not_run_yet(
    fresh_db,
    setup_accounts_fresh_db,
    setup_generic_asset_types_fresh_db,
    unowned_forecaster,
):
    """A source made for an automation has no beliefs yet, and the automation's asset names the organisation."""
    from flexmeasures.data.models.automations import Automation

    prosumer = setup_accounts_fresh_db["Prosumer"]
    sensor = _asset_with_sensor(
        fresh_db,
        prosumer,
        setup_generic_asset_types_fresh_db["battery"],
        "automated site",
    )
    fresh_db.session.add(
        Automation(
            asset_id=sensor.generic_asset_id,
            type="forecasting",
            name="Hourly forecasts",
            cronstr="0 * * * *",
            timezone="Europe/Amsterdam",
            generator_id=unowned_forecaster.id,
        )
    )
    fresh_db.session.flush()
    source_id = unowned_forecaster.id

    _migration().couple_sources_to_organisations(
        fresh_db.session.connection(), splitting=False
    )
    fresh_db.session.expire_all()

    assert fresh_db.session.get(DataSource, source_id).account_id == prosumer.id


def test_a_shared_source_stops_the_upgrade_and_names_what_to_look_at(
    fresh_db,
    setup_accounts_fresh_db,
    setup_generic_asset_types_fresh_db,
    unowned_forecaster,
):
    """Two organisations on one source cannot be resolved by guessing, so the upgrade says so rather than picking one."""
    prosumer = setup_accounts_fresh_db["Prosumer"]
    supplier = setup_accounts_fresh_db["Supplier"]
    for account, name in ((prosumer, "prosumer site"), (supplier, "supplier site")):
        sensor = _asset_with_sensor(
            fresh_db, account, setup_generic_asset_types_fresh_db["battery"], name
        )
        _record(fresh_db, sensor, unowned_forecaster, datetime(2026, 10, 1, tzinfo=utc))
    source_id = unowned_forecaster.id

    with pytest.raises(RuntimeError) as refusal:
        _migration().couple_sources_to_organisations(
            fresh_db.session.connection(), splitting=False
        )

    assert f"data source {source_id}" in str(refusal.value)
    assert "split-shared-sources=true" in str(refusal.value)
    assert str(prosumer.id) in str(refusal.value) and str(supplier.id) in str(
        refusal.value
    )


def test_splitting_moves_what_the_other_organisation_recorded_and_keeps_the_id(
    fresh_db,
    setup_accounts_fresh_db,
    setup_generic_asset_types_fresh_db,
    unowned_forecaster,
):
    """What a split moves, and what keeps the id it moved away from.

    Which organisation wins is pinned by `test_recency_is_when_a_belief_was_recorded_not_what_it_is_about`:
    these beliefs carry no horizon, so belief time and event start coincide here and this test cannot tell the two rules apart.
    """
    prosumer = setup_accounts_fresh_db["Prosumer"]
    supplier = setup_accounts_fresh_db["Supplier"]
    stale_sensor = _asset_with_sensor(
        fresh_db,
        prosumer,
        setup_generic_asset_types_fresh_db["battery"],
        "prosumer site",
    )
    fresh_sensor = _asset_with_sensor(
        fresh_db,
        supplier,
        setup_generic_asset_types_fresh_db["battery"],
        "supplier site",
    )
    _record(
        fresh_db, stale_sensor, unowned_forecaster, datetime(2026, 1, 1, tzinfo=utc)
    )
    _record(
        fresh_db, fresh_sensor, unowned_forecaster, datetime(2026, 10, 1, tzinfo=utc)
    )
    source_id = unowned_forecaster.id

    _migration().couple_sources_to_organisations(
        fresh_db.session.connection(), splitting=True
    )
    fresh_db.session.expire_all()

    kept = fresh_db.session.get(DataSource, source_id)
    assert (
        kept.account_id == supplier.id
    ), "one organisation keeps the id it was shared under"

    moved = fresh_db.session.scalars(
        select(DataSource).filter(
            DataSource.account_id == prosumer.id, DataSource.name == "Seita"
        )
    ).one()
    assert moved.id != source_id
    assert (
        moved.attributes == unowned_forecaster.attributes
    ), "the copy records under the same configuration"

    stale_beliefs = fresh_db.session.scalars(
        select(TimedBelief).filter_by(sensor_id=stale_sensor.id)
    ).all()
    assert [belief.source_id for belief in stale_beliefs] == [moved.id]
    fresh_beliefs = fresh_db.session.scalars(
        select(TimedBelief).filter_by(sensor_id=fresh_sensor.id)
    ).all()
    assert [belief.source_id for belief in fresh_beliefs] == [source_id]

    links = fresh_db.session.scalars(
        select(SensorDataSource).filter_by(sensor_id=stale_sensor.id)
    ).all()
    assert [link.source_id for link in links] == [moved.id]


def test_a_host_can_say_which_organisation_keeps_a_shared_sources_id(
    fresh_db,
    setup_accounts_fresh_db,
    setup_generic_asset_types_fresh_db,
    unowned_forecaster,
):
    """A source id can be referred to from configurations the upgrade cannot read, so the host can overrule freshness."""
    prosumer = setup_accounts_fresh_db["Prosumer"]
    supplier = setup_accounts_fresh_db["Supplier"]
    stale_sensor = _asset_with_sensor(
        fresh_db,
        prosumer,
        setup_generic_asset_types_fresh_db["battery"],
        "prosumer site",
    )
    fresh_sensor = _asset_with_sensor(
        fresh_db,
        supplier,
        setup_generic_asset_types_fresh_db["battery"],
        "supplier site",
    )
    _record(
        fresh_db, stale_sensor, unowned_forecaster, datetime(2026, 1, 1, tzinfo=utc)
    )
    _record(
        fresh_db, fresh_sensor, unowned_forecaster, datetime(2026, 10, 1, tzinfo=utc)
    )
    source_id = unowned_forecaster.id

    _migration().couple_sources_to_organisations(
        fresh_db.session.connection(),
        splitting=True,
        keepers={source_id: prosumer.id},
    )
    fresh_db.session.expire_all()

    kept = fresh_db.session.get(DataSource, source_id)
    assert (
        kept.account_id == prosumer.id
    ), "the named organisation keeps the id, not the freshest one"
    moved = fresh_db.session.scalars(
        select(DataSource).filter(
            DataSource.account_id == supplier.id, DataSource.name == "Seita"
        )
    ).one()
    assert [
        belief.source_id
        for belief in fresh_db.session.scalars(
            select(TimedBelief).filter_by(sensor_id=fresh_sensor.id)
        ).all()
    ] == [moved.id]


def test_keeping_a_source_with_an_organisation_that_never_used_it_is_refused(
    fresh_db,
    setup_accounts_fresh_db,
    setup_generic_asset_types_fresh_db,
    unowned_forecaster,
):
    """Naming an organisation which recorded nothing under the source is a typo, not an instruction."""
    prosumer = setup_accounts_fresh_db["Prosumer"]
    supplier = setup_accounts_fresh_db["Supplier"]
    dummy = setup_accounts_fresh_db["Dummy"]
    for account, name in ((prosumer, "prosumer site"), (supplier, "supplier site")):
        sensor = _asset_with_sensor(
            fresh_db, account, setup_generic_asset_types_fresh_db["battery"], name
        )
        _record(fresh_db, sensor, unowned_forecaster, datetime(2026, 10, 1, tzinfo=utc))

    with pytest.raises(RuntimeError, match="did not record under it"):
        _migration().couple_sources_to_organisations(
            fresh_db.session.connection(),
            splitting=True,
            keepers={unowned_forecaster.id: dummy.id},
        )


def test_the_x_argument_for_keeping_a_source_is_read_as_a_pair():
    """`-x keep-source=42:3` names a source and the organisation that keeps it, and says so when it does not."""
    migration = _migration()
    assert migration._keepers_from_x_arguments(
        ["split-shared-sources=true", "keep-source=42:3", "keep-source=7:1"]
    ) == {42: 3, 7: 1}
    with pytest.raises(RuntimeError, match="keep-source"):
        migration._keepers_from_x_arguments(["keep-source=42"])


def test_recency_is_when_a_belief_was_recorded_not_what_it_is_about(
    fresh_db,
    setup_accounts_fresh_db,
    setup_generic_asset_types_fresh_db,
    unowned_forecaster,
):
    """A generator records beliefs about the future, so the furthest event start is a horizon, not a recent run."""
    prosumer = setup_accounts_fresh_db["Prosumer"]
    supplier = setup_accounts_fresh_db["Supplier"]
    long_horizon = _asset_with_sensor(
        fresh_db,
        prosumer,
        setup_generic_asset_types_fresh_db["battery"],
        "prosumer site",
    )
    recent_run = _asset_with_sensor(
        fresh_db,
        supplier,
        setup_generic_asset_types_fresh_db["battery"],
        "supplier site",
    )
    # Ran on 1 September looking 60 days ahead: the furthest event start of the two, and the older run by a month.
    _record(
        fresh_db,
        long_horizon,
        unowned_forecaster,
        datetime(2026, 10, 31, tzinfo=utc),
        belief_horizon=timedelta(days=60),
    )
    # Ran on 1 October looking an hour ahead: the nearer event start, and the more recent run.
    _record(
        fresh_db,
        recent_run,
        unowned_forecaster,
        datetime(2026, 10, 1, 1, tzinfo=utc),
        belief_horizon=timedelta(hours=1),
    )
    source_id = unowned_forecaster.id

    _migration().couple_sources_to_organisations(
        fresh_db.session.connection(), splitting=True
    )
    fresh_db.session.expire_all()

    assert (
        fresh_db.session.get(DataSource, source_id).account_id == supplier.id
    ), "the organisation whose run is most recent keeps the id, not the one forecasting furthest ahead"


def test_a_sensor_link_left_behind_by_deleted_beliefs_does_not_stop_the_upgrade(
    fresh_db,
    setup_accounts_fresh_db,
    setup_generic_asset_types_fresh_db,
    unowned_forecaster,
):
    """`sensor_data_source` keeps a pair after its beliefs are deleted, so it alone cannot say a source is still shared."""
    prosumer = setup_accounts_fresh_db["Prosumer"]
    supplier = setup_accounts_fresh_db["Supplier"]
    current = _asset_with_sensor(
        fresh_db,
        prosumer,
        setup_generic_asset_types_fresh_db["battery"],
        "prosumer site",
    )
    former = _asset_with_sensor(
        fresh_db,
        supplier,
        setup_generic_asset_types_fresh_db["battery"],
        "supplier site",
    )
    _record(fresh_db, current, unowned_forecaster, datetime(2026, 10, 1, tzinfo=utc))
    _record(fresh_db, former, unowned_forecaster, datetime(2026, 1, 1, tzinfo=utc))
    # The supplier's beliefs are deleted, as data is; the summary row stays behind, as it does.
    fresh_db.session.query(TimedBelief).filter_by(sensor_id=former.id).delete()
    fresh_db.session.flush()
    assert fresh_db.session.scalars(
        select(SensorDataSource).filter_by(sensor_id=former.id)
    ).all(), "the sensor link outlives the beliefs"
    source_id = unowned_forecaster.id

    _migration().couple_sources_to_organisations(
        fresh_db.session.connection(), splitting=False
    )
    fresh_db.session.expire_all()

    assert (
        fresh_db.session.get(DataSource, source_id).account_id == prosumer.id
    ), "the source is coupled to the organisation it still records for"


def test_a_source_whose_every_claim_is_stale_is_left_alone(
    fresh_db,
    setup_accounts_fresh_db,
    setup_generic_asset_types_fresh_db,
    unowned_forecaster,
):
    """Only the sensor-link summary is left of such a source, so splitting it would make sources that receive nothing."""
    prosumer = setup_accounts_fresh_db["Prosumer"]
    supplier = setup_accounts_fresh_db["Supplier"]
    for account, name in ((prosumer, "prosumer site"), (supplier, "supplier site")):
        sensor = _asset_with_sensor(
            fresh_db, account, setup_generic_asset_types_fresh_db["battery"], name
        )
        _record(fresh_db, sensor, unowned_forecaster, datetime(2026, 1, 1, tzinfo=utc))
    fresh_db.session.query(TimedBelief).filter_by(
        source_id=unowned_forecaster.id
    ).delete()
    fresh_db.session.flush()
    source_id = unowned_forecaster.id

    # No refusal: there is nothing left for a host to look at.
    _migration().couple_sources_to_organisations(
        fresh_db.session.connection(), splitting=False
    )
    fresh_db.session.expire_all()

    assert fresh_db.session.get(DataSource, source_id).account_id is None
    assert fresh_db.session.scalars(
        select(DataSource).filter(DataSource.name == "Seita")
    ).all() == [
        fresh_db.session.get(DataSource, source_id)
    ], "and no sources were made for organisations that would receive nothing"
