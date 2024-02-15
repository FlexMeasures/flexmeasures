"""
Populate the database with data we know or read in.
"""
from __future__ import annotations

from pathlib import Path
from shutil import rmtree
from datetime import datetime, timedelta

import pandas as pd
from flask import current_app as app
from flask_sqlalchemy import SQLAlchemy
import click
from sqlalchemy import func, and_, select, delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.serializer import loads, dumps
from timetomodel.forecasting import make_rolling_forecasts
from timetomodel.exceptions import MissingData, NaNData
from humanize import naturaldelta
import inflect

from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.models.generic_assets import GenericAssetType, GenericAsset
from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.models.user import User, Role, RolesUsers, AccountRole
from flexmeasures.data.models.forecasting import lookup_model_specs_configurator
from flexmeasures.data.models.forecasting.exceptions import NotEnoughDataException
from flexmeasures.utils.time_utils import ensure_local_timezone
from flexmeasures.data.transactional import as_transaction
from flexmeasures.cli.utils import MsgStyle


BACKUP_PATH = app.config.get("FLEXMEASURES_DB_BACKUP_PATH")
LOCAL_TIME_ZONE = app.config.get("FLEXMEASURES_TIMEZONE")

infl_eng = inflect.engine()


def add_default_data_sources(db: SQLAlchemy):
    for source_name, source_type in (
        ("Seita", "demo script"),
        ("Seita", "forecaster"),
        ("Seita", "scheduler"),
    ):
        source = db.session.execute(
            select(DataSource).filter(
                and_(DataSource.name == source_name, DataSource.type == source_type)
            )
        ).scalar_one_or_none()
        if source:
            click.echo(f"Source {source_name} ({source_type}) already exists.")
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
    for role_name, role_description in (
        ("admin", "Super user"),
        ("admin-reader", "Can read everything"),
        ("account-admin", "Can post and edit sensors and assets in their account"),
        ("consultant", "Can read everything in consultancy client accounts"),
    ):
        role = db.session.execute(
            select(Role).filter_by(name=role_name)
        ).scalar_one_or_none()
        if role:
            click.echo(f"Role {role_name} already exists.")
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


@as_transaction  # noqa: C901
def populate_time_series_forecasts(  # noqa: C901
    db: SQLAlchemy,
    sensor_ids: list[int],
    horizons: list[timedelta],
    forecast_start: datetime,
    forecast_end: datetime,
    event_resolution: timedelta | None = None,
):
    training_and_testing_period = timedelta(days=30)

    click.echo(
        "Populating the database %s with time series forecasts of %s ahead ..."
        % (db.engine, infl_eng.join([naturaldelta(horizon) for horizon in horizons]))
    )

    # Set a data source for the forecasts
    data_source = db.session.execute(
        select(DataSource).filter_by(name="Seita", type="demo script")
    ).scalar_one_or_none()
    # List all sensors for which to forecast.
    sensors = [
        db.session.execute(
            select(Sensor).filter(Sensor.id.in_(sensor_ids))
        ).scalar_one_or_none()
    ]
    if not sensors:
        click.echo("No such sensors in db, so I will not add any forecasts.")
        return

    # Make a model for each sensor and horizon, make rolling forecasts and save to database.
    # We cannot use (faster) bulk save, as forecasts might become regressors in other forecasts.
    for sensor in sensors:
        for horizon in horizons:
            try:
                default_model = lookup_model_specs_configurator()
                model_specs, model_identifier, model_fallback = default_model(
                    sensor=sensor,
                    forecast_start=forecast_start,
                    forecast_end=forecast_end,
                    forecast_horizon=horizon,
                    custom_model_params=dict(
                        training_and_testing_period=training_and_testing_period,
                        event_resolution=event_resolution,
                    ),
                )
                click.echo(
                    "Computing forecasts of %s ahead for sensor %s, "
                    "from %s to %s with a training and testing period of %s, using %s ..."
                    % (
                        naturaldelta(horizon),
                        sensor.id,
                        forecast_start,
                        forecast_end,
                        naturaldelta(training_and_testing_period),
                        model_identifier,
                    )
                )
                model_specs.creation_time = forecast_start
                forecasts, model_state = make_rolling_forecasts(
                    start=forecast_start, end=forecast_end, model_specs=model_specs
                )
                # Upsample to sensor resolution if needed
                if forecasts.index.freq > pd.Timedelta(sensor.event_resolution):
                    forecasts = model_specs.outcome_var.resample_data(
                        forecasts,
                        time_window=(forecasts.index.min(), forecasts.index.max()),
                        expected_frequency=sensor.event_resolution,
                    )
            except (NotEnoughDataException, MissingData, NaNData) as e:
                click.echo("Skipping forecasts for sensor %s: %s" % (sensor, str(e)))
                continue

            beliefs = [
                TimedBelief(
                    event_start=ensure_local_timezone(dt, tz_name=LOCAL_TIME_ZONE),
                    belief_horizon=horizon,
                    event_value=value,
                    sensor=sensor,
                    source=data_source,
                )
                for dt, value in forecasts.items()
            ]

            click.echo(
                "Saving %s %s-forecasts for %s..."
                % (len(beliefs), naturaldelta(horizon), sensor.id)
            )
            for belief in beliefs:
                db.session.add(belief)

    click.echo(
        "DB now has %d forecasts"
        % db.session.scalar(
            select(func.count())
            .select_from(TimedBelief)
            .filter(TimedBelief.belief_horizon > timedelta(hours=0))
        )
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
    sensor_id: id | None = None,
):
    click.echo("Deleting (time series) data from the database %s ..." % db.engine)

    query = delete(TimedBelief).filter(TimedBelief.belief_horizon <= timedelta(hours=0))
    if sensor_id is not None:
        query = query.filter(TimedBelief.sensor_id == sensor_id)
    num_measurements_deleted = db.session.execute(query)

    click.echo("Deleted %d measurements (ex-post beliefs)" % num_measurements_deleted)


@as_transaction
def depopulate_prognoses(
    db: SQLAlchemy,
    sensor_id: id | None = None,
):
    """
    Delete all prognosis data (with an horizon > 0).
    This affects forecasts as well as schedules.

    Pass a sensor ID to restrict to data on one sensor only.

    If no sensor is specified, this function also deletes forecasting and scheduling jobs.
    (Doing this only for jobs which forecast/schedule one sensor is not implemented and also tricky.)
    """
    click.echo(
        "Deleting (time series) forecasts and schedules data from the database %s ..."
        % db.engine
    )

    if not sensor_id:
        num_forecasting_jobs_deleted = app.queues["forecasting"].empty()
        num_scheduling_jobs_deleted = app.queues["scheduling"].empty()

    # Clear all forecasts (data with positive horizon)
    query = delete(TimedBelief).filter(TimedBelief.belief_horizon > timedelta(hours=0))

    if sensor_id is not None:
        query = query.filter(TimedBelief.sensor_id == sensor_id)
    num_forecasts_deleted = db.session.execute(query)

    if not sensor_id:
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


def save_tables(
    db: SQLAlchemy,
    backup_name: str = "",
    structure: bool = True,
    data: bool = False,
    backup_path: str = BACKUP_PATH,
):
    # Make a new folder for the backup
    backup_folder = Path("%s/%s" % (backup_path, backup_name))
    try:
        backup_folder.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        click.echo(
            "Can't save backup, because directory %s/%s already exists."
            % (backup_path, backup_name)
        )
        return

    affected_classes = get_affected_classes(structure, data)
    c = None
    try:
        for c in affected_classes:
            file_path = "%s/%s/%s.obj" % (backup_path, backup_name, c.__tablename__)

            with open(file_path, "xb") as file_handler:
                file_handler.write(dumps(db.session.scalars(select(c))).all())
            click.echo("Successfully saved %s/%s." % (backup_name, c.__tablename__))
    except SQLAlchemyError as e:
        click.echo(
            "Can't save table %s because of the following error:\n\n\t%s\n\nCleaning up..."
            % (c.__tablename__, e)
        )
        rmtree(backup_folder)
        click.echo("Removed directory %s/%s." % (backup_path, backup_name))


@as_transaction
def load_tables(
    db: SQLAlchemy,
    backup_name: str = "",
    structure: bool = True,
    data: bool = False,
    backup_path: str = BACKUP_PATH,
):
    if (
        Path("%s/%s" % (backup_path, backup_name)).exists()
        and Path("%s/%s" % (backup_path, backup_name)).is_dir()
    ):
        affected_classes = get_affected_classes(structure, data)
        statement = "SELECT sequence_name from information_schema.sequences;"
        data = db.session.execute(statement).fetchall()
        sequence_names = [s.sequence_name for s in data]
        for c in affected_classes:
            file_path = "%s/%s/%s.obj" % (backup_path, backup_name, c.__tablename__)
            sequence_name = "%s_id_seq" % c.__tablename__
            try:
                with open(file_path, "rb") as file_handler:
                    for row in loads(file_handler.read()):
                        db.session.merge(row)
                if sequence_name in sequence_names:

                    # Get max id
                    max_id = db.session.execute(
                        select(func.max(c.id)).select_from(c)
                    ).scalar_one_or_none()
                    max_id = 1 if max_id is None else max_id

                    # Set table seq to max id
                    db.engine.execute(
                        "SELECT setval('%s', %s, true);" % (sequence_name, max_id)
                    )

                click.echo(
                    "Successfully loaded %s/%s." % (backup_name, c.__tablename__)
                )
            except FileNotFoundError:
                click.echo(
                    "Can't load table, because filename %s does not exist."
                    % c.__tablename__
                )
    else:
        click.echo(
            "Can't load backup, because directory %s/%s does not exist."
            % (backup_path, backup_name)
        )


def get_affected_classes(structure: bool = True, data: bool = False) -> list:
    affected_classes = []
    if structure:
        affected_classes += [
            Role,
            User,
            RolesUsers,
            Sensor,
            GenericAssetType,
            GenericAsset,
            DataSource,
        ]
    if data:
        affected_classes += [TimedBelief]
    return affected_classes
