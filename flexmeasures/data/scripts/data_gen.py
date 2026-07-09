"""
Populate the database with data we know or read in.
"""

from __future__ import annotations

from datetime import timedelta

from flask import current_app as app
from flask_sqlalchemy import SQLAlchemy
import click
from sqlalchemy import func, and_, select, delete

from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.generic_assets import GenericAssetType, GenericAsset
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.user import User, Role, AccountRole
from flexmeasures.data.transactional import as_transaction
from flexmeasures.cli.utils import MsgStyle
from flexmeasures.data.utils import TEMPLATE_COPY_GUIDANCE_PREFIX


def add_default_data_sources(db: SQLAlchemy):
    for source_name, source_type in (
        ("Seita", "demo script"),
        ("Seita", "forecaster"),
        ("Seita", "scheduler"),
    ):
        sources = db.session.execute(
            select(DataSource).filter(
                and_(DataSource.name == source_name, DataSource.type == source_type)
            )
        ).scalar()
        if sources:
            click.echo(f"A source {source_name} ({source_type}) already exists.")
        else:
            db.session.add(DataSource(name=source_name, type=source_type))


def add_default_asset_types(db: SQLAlchemy) -> dict[str, GenericAssetType]:
    """
    Add a few useful asset types.
    """
    types = {}
    for type_name, type_description in (
        ("solar", "solar panel(s)"),
        ("wind", "wind turbine"),
        ("one-way_evse", "uni-directional Electric Vehicle Supply Equipment"),
        ("two-way_evse", "bi-directional Electric Vehicle Supply Equipment"),
        ("battery", "stationary battery"),
        ("building", "building"),
        ("process", "process"),
        ("heat-storage", "thermal storage / buffer"),
    ):
        _type = db.session.execute(
            select(GenericAssetType).filter_by(name=type_name)
        ).scalar_one_or_none()
        if _type is None:
            _type = GenericAssetType(name=type_name, description=type_description)
            db.session.add(_type)
            click.secho(
                f"Generic asset type `{type_name}` created successfully.",
                **MsgStyle.SUCCESS,
            )

        types[type_name] = _type
    return types


def add_default_user_roles(db: SQLAlchemy):
    """
    Add a few useful user roles.
    """
    from flexmeasures.auth import policy as auth_policy

    for role_name, role_description in (
        (auth_policy.ADMIN_ROLE, "Super user"),
        (auth_policy.ADMIN_READER_ROLE, "Can read everything"),
        (
            auth_policy.ACCOUNT_ADMIN_ROLE,
            "Can update and delete data in their account (e.g. assets, sensors, users, beliefs)",
        ),
        (
            auth_policy.CONSULTANT_ROLE,
            "Can read everything in consultancy client accounts",
        ),
    ):
        role = db.session.execute(
            select(Role).filter_by(name=role_name)
        ).scalar_one_or_none()
        if role:
            click.echo(f"User role {role_name} already exists.")
        else:
            db.session.add(Role(name=role_name, description=role_description))


def add_default_account_roles(db: SQLAlchemy):
    """
    Add a few useful account roles, inspired by USEF.
    """
    for role_name, role_description in (
        ("Prosumer", "A consumer who might also produce"),
        ("MDC", "Metering Data Company"),
        ("Supplier", "Supplier of energy"),
        ("Aggregator", "Aggregator of energy flexibility"),
        ("ESCO", "Energy Service Company"),
    ):
        role = db.session.execute(
            select(AccountRole).filter_by(name=role_name)
        ).scalar_one_or_none()
        if role:
            click.echo(f"Account role {role_name} already exists.")
        else:
            db.session.add(AccountRole(name=role_name, description=role_description))


def add_transmission_zone_asset(country_code: str, db: SQLAlchemy) -> GenericAsset:
    """
    Ensure a GenericAsset exists to model a transmission zone for a country.
    """
    transmission_zone_type = db.session.execute(
        select(GenericAssetType).filter_by(name="transmission zone")
    ).scalar_one_or_none()
    if not transmission_zone_type:
        click.echo("Adding transmission zone type ...")
        transmission_zone_type = GenericAssetType(
            name="transmission zone",
            description="A grid regulated & balanced as a whole, usually a national grid.",
        )
        db.session.add(transmission_zone_type)
    ga_name = f"{country_code} transmission zone"
    transmission_zone = db.session.execute(
        select(GenericAsset).filter_by(name=ga_name)
    ).scalar_one_or_none()
    if not transmission_zone:
        click.echo(f"Adding {ga_name} ...")
        transmission_zone = GenericAsset(
            name=ga_name,
            generic_asset_type=transmission_zone_type,
            account_id=None,  # public
        )
        db.session.add(transmission_zone)
    return transmission_zone


def _ensure_public_root_asset(
    db: SQLAlchemy,
    *,
    name: str,
    asset_type: GenericAssetType,
    description: str,
    flex_model: dict | None = None,
    attributes: dict | None = None,
    sensors_to_show: list | None = None,
) -> GenericAsset:
    """Create or update a public root asset used as a template."""
    asset = db.session.execute(
        select(GenericAsset).filter_by(
            name=name,
            account_id=None,
            parent_asset_id=None,
        )
    ).scalar_one_or_none()

    if asset is None:
        asset = GenericAsset(
            name=name,
            generic_asset_type=asset_type,
            account_id=None,
        )
        db.session.add(asset)
        db.session.flush()

    asset.generic_asset_type = asset_type
    asset.description = description
    if attributes:
        asset.attributes = dict(asset.attributes or {})
        asset.attributes.update(attributes)
    if flex_model is not None:
        asset.flex_model = flex_model
    if sensors_to_show is not None:
        asset.sensors_to_show = sensors_to_show
    return asset


def _ensure_sensor(
    db: SQLAlchemy,
    *,
    asset: GenericAsset,
    name: str,
    unit: str,
    event_resolution: timedelta,
    attributes: dict | None = None,
) -> Sensor:
    """Create or update one sensor for a template asset."""
    sensor = db.session.execute(
        select(Sensor).filter_by(name=name, generic_asset_id=asset.id)
    ).scalar_one_or_none()
    if sensor is None:
        sensor = Sensor(
            name=name,
            generic_asset=asset,
            unit=unit,
            timezone="Europe/Amsterdam",
            event_resolution=event_resolution,
        )
        db.session.add(sensor)
        db.session.flush()

    sensor.unit = unit
    sensor.timezone = "Europe/Amsterdam"
    sensor.event_resolution = event_resolution
    if attributes:
        sensor.attributes = dict(sensor.attributes or {})
        sensor.attributes.update(attributes)
    return sensor


def _template_metadata(template_key: str) -> dict:
    """Return the metadata block used to tag built-in asset templates."""
    return {
        "template": {
            "key": template_key,
            "kind": "single-asset",
            "has_scenarios": False,
        }
    }


@as_transaction
def provision_default_template_assets(db: SQLAlchemy):
    """Ensure the default starter template assets exist.

    This currently provisions the single-asset starter templates which are
    intended to show up in the asset copy UI.
    """
    asset_types = add_default_asset_types(db)

    # Battery
    battery = _ensure_public_root_asset(
        db,
        name="Battery Template",
        asset_type=asset_types["battery"],
        description=(
            "Single battery asset with example power and state-of-charge sensors, "
            f"plus a basic storage flex-model. {TEMPLATE_COPY_GUIDANCE_PREFIX} to "
            "start modeling a battery."
        ),
        attributes=_template_metadata("battery-template"),
    )
    battery_power = _ensure_sensor(
        db,
        asset=battery,
        name="electricity-power",
        unit="kW",
        event_resolution=timedelta(minutes=15),
        attributes={"consumption_is_positive": True, "template_role": "power"},
    )
    battery_soc = _ensure_sensor(
        db,
        asset=battery,
        name="state-of-charge",
        unit="kWh",
        event_resolution=timedelta(0),
        attributes={"template_role": "state-of-charge"},
    )
    battery.flex_model = {
        "soc-max": "450 kWh",
        "soc-min": "50 kWh",
        "roundtrip-efficiency": "90%",
        "power-capacity": "500 kW",
        "state-of-charge": {"sensor": battery_soc.id},
    }
    battery.sensors_to_show = [
        {"title": "Power", "plots": [{"sensor": battery_power.id}]},
        {"title": "State of charge", "plots": [{"sensor": battery_soc.id}]},
    ]

    # EV charger
    ev_charger = _ensure_public_root_asset(
        db,
        name="EV Charger Template",
        asset_type=asset_types["one-way_evse"],
        description=(
            "Single EV charger asset with example charging power and state-of-charge "
            "sensors, plus a simple charging flex-model. "
            f"{TEMPLATE_COPY_GUIDANCE_PREFIX} to start building a charger or EV "
            "charging setup."
        ),
        attributes=_template_metadata("ev-charger-template"),
    )
    ev_power = _ensure_sensor(
        db,
        asset=ev_charger,
        name="electricity-power",
        unit="kW",
        event_resolution=timedelta(minutes=15),
        attributes={"consumption_is_positive": True, "template_role": "power"},
    )
    ev_soc = _ensure_sensor(
        db,
        asset=ev_charger,
        name="state-of-charge",
        unit="kWh",
        event_resolution=timedelta(0),
        attributes={"template_role": "state-of-charge"},
    )
    ev_charger.flex_model = {
        "soc-max": "60 kWh",
        "soc-min": "0 kWh",
        "soc-minima": [{"value": "12 kWh"}],
        "roundtrip-efficiency": "90%",
        "power-capacity": "11 kW",
        "production-capacity": "0 kW",
        "state-of-charge": {"sensor": ev_soc.id},
    }
    ev_charger.sensors_to_show = [
        {"title": "Power", "plots": [{"sensor": ev_power.id}]},
        {"title": "State of charge", "plots": [{"sensor": ev_soc.id}]},
    ]

    # Heat pump / buffer
    heat_pump = _ensure_public_root_asset(
        db,
        name="Heat Pump Template",
        asset_type=asset_types["heat-storage"],
        description=(
            "Single heat-pump-with-buffer style asset, represented as thermal storage "
            "with example power and thermal state-of-charge sensors. "
            f"{TEMPLATE_COPY_GUIDANCE_PREFIX} to start modeling heat flexibility."
        ),
        attributes=_template_metadata("heat-pump-template"),
    )
    heat_power = _ensure_sensor(
        db,
        asset=heat_pump,
        name="electricity-power",
        unit="kW",
        event_resolution=timedelta(minutes=15),
        attributes={"consumption_is_positive": True, "template_role": "power"},
    )
    heat_soc = _ensure_sensor(
        db,
        asset=heat_pump,
        name="state-of-charge",
        unit="kWh",
        event_resolution=timedelta(0),
        attributes={"template_role": "state-of-charge"},
    )
    heat_pump.flex_model = {
        "soc-max": "15 kWh",
        "soc-min": "0 kWh",
        "charging-efficiency": "300 %",
        "storage-efficiency": "99.3 %",
        "consumption-capacity": "5 kW",
        "production-capacity": "0 kW",
        "power-capacity": "5 kW",
        "state-of-charge": {"sensor": heat_soc.id},
    }
    heat_pump.sensors_to_show = [
        {"title": "Power", "plots": [{"sensor": heat_power.id}]},
        {"title": "State of charge", "plots": [{"sensor": heat_soc.id}]},
    ]


# ------------ Main functions --------------------------------
# These can registered at the app object as cli functions


@as_transaction
def populate_initial_structure(db: SQLAlchemy):
    """
    Add initially useful structural data.
    """
    click.echo("Populating the database %s with structural data ..." % db.engine)
    add_default_data_sources(db)
    add_default_user_roles(db)
    add_default_account_roles(db)
    add_default_asset_types(db)
    click.echo(
        "DB now has %d DataSource(s)"
        % db.session.scalar(select(func.count()).select_from(DataSource))
    )

    click.echo(
        "DB now has %d AssetType(s)"
        % db.session.scalar(select(func.count()).select_from(GenericAssetType))
    )
    click.echo(
        "DB now has %d Role(s) for users"
        % db.session.scalar(select(func.count()).select_from(Role))
    )
    click.echo(
        "DB now has %d AccountRole(s)"
        % db.session.scalar(select(func.count()).select_from(AccountRole))
    )


@as_transaction
def depopulate_structure(db: SQLAlchemy):
    click.echo("Depopulating structural data from the database %s ..." % db.engine)
    num_assets_deleted = db.session.execute(delete(GenericAsset))
    num_asset_types_deleted = db.session.execute(delete(GenericAssetType))

    num_data_sources_deleted = db.session.execute(delete(DataSource))
    num_roles_deleted = db.session.execute(delete(Role))
    num_users_deleted = db.session.execute(delete(User))
    click.echo("Deleted %d AssetTypes" % num_asset_types_deleted)
    click.echo("Deleted %d Assets" % num_assets_deleted)
    click.echo("Deleted %d DataSources" % num_data_sources_deleted)
    click.echo("Deleted %d Roles" % num_roles_deleted)
    click.echo("Deleted %d Users" % num_users_deleted)


@as_transaction
def depopulate_measurements(
    db: SQLAlchemy,
    sensor: Sensor | None = None,
):
    click.echo("Deleting (time series) data from the database %s ..." % db.engine)

    query = delete(TimedBelief).filter(TimedBelief.belief_horizon <= timedelta(hours=0))
    if sensor is not None:
        query = query.filter(TimedBelief.sensor_id == sensor.id)
    deletion_result = db.session.execute(query)
    num_measurements_deleted = deletion_result.rowcount

    click.echo("Deleted %d measurements (ex-post beliefs)" % num_measurements_deleted)


@as_transaction
def depopulate_prognoses(
    db: SQLAlchemy,
    sensor: Sensor | None = None,
):
    """
    Delete all prognosis data (with a horizon > 0).
    This affects forecasts as well as schedules.

    Pass a sensor to restrict to data on one sensor only.

    If no sensor is specified, this function also deletes forecasting and scheduling jobs.
    (Doing this only for jobs which forecast/schedule one sensor is not implemented and also tricky.)
    """
    click.echo(
        "Deleting (time series) forecasts and schedules data from the database %s ..."
        % db.engine
    )

    if not sensor:
        num_forecasting_jobs_deleted = app.queues["forecasting"].empty()
        num_scheduling_jobs_deleted = app.queues["scheduling"].empty()

    # Clear all forecasts (data with positive horizon)
    query = delete(TimedBelief).filter(TimedBelief.belief_horizon > timedelta(hours=0))

    if sensor is not None:
        query = query.filter(TimedBelief.sensor_id == sensor.id)
    deletion_result = db.session.execute(query)
    num_forecasts_deleted = deletion_result.rowcount

    if not sensor:
        click.echo("Deleted %d Forecast Jobs" % num_forecasting_jobs_deleted)
        click.echo("Deleted %d Schedule Jobs" % num_scheduling_jobs_deleted)
    click.echo("Deleted %d forecasts (ex-ante beliefs)" % num_forecasts_deleted)


def reset_db(db: SQLAlchemy):
    db.session.commit()  # close any existing sessions
    click.echo("Dropping everything in %s ..." % db.engine)
    db.reflect()  # see http://jrheard.tumblr.com/post/12759432733/dropping-all-tables-on-postgres-using
    db.drop_all()
    click.echo("Recreating everything ...")
    db.create_all()
    click.echo("Committing ...")
    db.session.commit()
