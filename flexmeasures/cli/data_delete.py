"""
CLI commands for removing data
"""

from __future__ import annotations

from datetime import datetime, timedelta
from itertools import chain

import click
from flask import current_app as app
from flask.cli import with_appcontext
from timely_beliefs.beliefs.queries import query_unchanged_beliefs
from sqlalchemy import delete, func, select


from flexmeasures.data import db
from flexmeasures.data.models.user import Account, AccountRole, RolesAccounts, User
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.schemas import AwareDateTimeField, SensorIdField, AssetIdField
from flexmeasures.data.services.users import find_user_by_email, delete_user
from flexmeasures.cli.utils import (
    abort,
    done,
    DeprecatedOption,
    DeprecatedOptionsCommand,
)
from flexmeasures.utils.flexmeasures_inflection import join_words_into_a_list


@click.group("delete")
def fm_delete_data():
    """FlexMeasures: Delete data."""


@fm_delete_data.command("account-role")
@with_appcontext
@click.option("--name", required=True)
def delete_account_role(name: str):
    """
    Delete an account role.
    If it has accounts connected, print them before deleting the connection.
    """
    role: AccountRole = db.session.execute(
        select(AccountRole).filter_by(name=name)
    ).scalar_one_or_none()
    if role is None:
        abort(f"Account role '{name}' does not exist.")
    accounts = role.accounts.all()
    if len(accounts) > 0:
        click.secho(
            f"The following accounts have role '{role.name}': {','.join([a.name for a in accounts])}. Removing this role from them ...",
        )
        for account in accounts:
            account.account_roles.remove(role)
    db.session.execute(delete(AccountRole).filter_by(id=role.id))
    db.session.commit()
    done(f"Account role '{name}' has been deleted.")


@fm_delete_data.command("account")
@with_appcontext
@click.option("--id", type=int)
@click.option(
    "--force/--no-force", default=False, help="Skip warning about consequences."
)
def delete_account(id: int, force: bool):
    """
    Delete an account, including their users & data.
    """
    account: Account = db.session.get(Account, id)
    if account is None:
        abort(f"Account with ID '{id}' does not exist.")
    if not force:
        prompt = f"Delete account '{account.name}', including generic assets, users and all their data?\n"
        users = db.session.scalars(select(User).filter_by(account_id=id)).all()
        if users:
            prompt += "Affected users: " + ",".join([u.username for u in users]) + "\n"
        generic_assets = db.session.scalars(
            select(GenericAsset).filter_by(account_id=id)
        ).all()
        if generic_assets:
            prompt += (
                "Affected generic assets: "
                + ",".join([ga.name for ga in generic_assets])
                + "\n"
            )
        click.confirm(prompt, abort=True)
    for user in account.users:
        click.secho(f"Deleting user {user} ...")
        delete_user(user)
    for role_account_association in db.session.scalars(
        select(RolesAccounts).filter_by(account_id=account.id)
    ).all():
        role = db.session.get(AccountRole, role_account_association.role_id)
        click.echo(
            f"Deleting association of account {account.name} and role {role.name} ...",
        )
        db.session.execute(
            delete(RolesAccounts).filter_by(
                account_id=role_account_association.account_id
            )
        )
    for asset in account.generic_assets:
        click.echo(f"Deleting generic asset {asset} (and sensors & beliefs) ...")
        db.session.execute(delete(GenericAsset).filter_by(id=asset.id))
    account_name = account.name
    db.session.execute(delete(Account).filter_by(id=account.id))
    db.session.commit()
    done(f"Account {account_name} has been deleted.")


@fm_delete_data.command("user")
@with_appcontext
@click.option("--email")
@click.option(
    "--force/--no-force", default=False, help="Skip warning about consequences."
)
def delete_a_user(email: str, force: bool):
    """
    Delete a user & also their assets and data.
    """
    if not force:
        prompt = f"Delete user '{email}'?"
        click.confirm(prompt, abort=True)
    the_user = find_user_by_email(email)
    if the_user is None:
        abort(f"Could not find user with email address '{email}' ...")
    delete_user(the_user)
    db.session.commit()


@fm_delete_data.command("asset")
@with_appcontext
@click.option("--id", "asset", type=AssetIdField())
@click.option(
    "--force/--no-force", default=False, help="Skip warning about consequences."
)
def delete_asset_and_data(asset: GenericAsset, force: bool):
    """
    Delete an asset & also its sensors and data.
    """
    if not force:
        prompt = (
            f"Delete {asset.__repr__()}, including all its sensors, data and children?"
        )
        click.confirm(prompt, abort=True)
    db.session.execute(delete(GenericAsset).filter_by(id=asset.id))
    db.session.commit()


@fm_delete_data.command("structure")
@with_appcontext
@click.option(
    "--force/--no-force", default=False, help="Skip warning about consequences."
)
def delete_structure(force):
    """
    Delete all structural (non time-series) data like assets (types),
    sources, roles and users.
    """
    if not force:
        click.confirm(
            f"Sure to delete all asset(type)s, sources, roles and users from {db.engine}?",
            abort=True,
        )
    from flexmeasures.data.scripts.data_gen import depopulate_structure

    depopulate_structure(db)


@fm_delete_data.command("measurements", cls=DeprecatedOptionsCommand)
@with_appcontext
@click.option(
    "--sensor",
    "--sensor-id",
    "sensor_id",
    type=int,
    cls=DeprecatedOption,
    deprecated=["--sensor-id"],
    preferred="--sensor",
    help="Delete (time series) data for a single sensor only. Follow up with the sensor's ID.",
)
@click.option(
    "--force/--no-force", default=False, help="Skip warning about consequences."
)
def delete_measurements(
    force: bool,
    sensor_id: int | None = None,
):
    """Delete measurements (ex-post beliefs, i.e. with belief_horizon <= 0)."""
    if not force:
        click.confirm(f"Sure to delete all measurements from {db.engine}?", abort=True)
    from flexmeasures.data.scripts.data_gen import depopulate_measurements

    depopulate_measurements(db, sensor_id)


@fm_delete_data.command("prognoses", cls=DeprecatedOptionsCommand)
@with_appcontext
@click.option(
    "--force/--no-force", default=False, help="Skip warning about consequences."
)
@click.option(
    "--sensor",
    "--sensor-id",
    "sensor_id",
    type=int,
    cls=DeprecatedOption,
    deprecated=["--sensor-id"],
    preferred="--sensor",
    help="Delete (time series) data for a single sensor only. Follow up with the sensor's ID. ",
)
def delete_prognoses(
    force: bool,
    sensor_id: int | None = None,
):
    """Delete forecasts and schedules (ex-ante beliefs, i.e. with belief_horizon > 0)."""
    if not force:
        click.confirm(f"Sure to delete all prognoses from {db.engine}?", abort=True)
    from flexmeasures.data.scripts.data_gen import depopulate_prognoses

    depopulate_prognoses(db, sensor_id)


@fm_delete_data.command("beliefs")
@with_appcontext
@click.option(
    "--asset",
    "generic_assets",
    required=False,
    multiple=True,
    type=AssetIdField(),
    help="Delete all beliefs associated with (sensors of) this asset.",
)
@click.option(
    "--sensor",
    "sensors",
    required=False,
    multiple=True,
    type=SensorIdField(),
    help="Delete all beliefs associated with this sensor.",
)
@click.option(
    "--start",
    "start",
    type=AwareDateTimeField(),
    required=False,
    help="Remove beliefs about events starting at this datetime. Follow up with a timezone-aware datetime in ISO 6801 format.",
)
@click.option(
    "--end",
    "end",
    type=AwareDateTimeField(),
    required=False,
    help="Remove beliefs about events ending at this datetime. Follow up with a timezone-aware datetime in ISO 6801 format.",
)
@click.option("--offspring", type=bool, required=False, default=False, is_flag=True)
def delete_beliefs(  # noqa: C901
    generic_assets: list[GenericAsset],
    sensors: list[Sensor],
    start: datetime | None = None,
    end: datetime | None = None,
    offspring: bool = False,
):
    """Delete all beliefs recorded on a given sensor (or on sensors of a given asset)."""

    # Validate input
    if not generic_assets and not sensors:
        abort("Must pass at least one sensor or asset.")
    elif generic_assets and sensors:
        abort("Passing both sensors and assets at the same time is not supported.")
    if start is not None and end is not None and start > end:
        abort("Start should not exceed end.")
    if offspring and len(generic_assets) == 0:
        abort("Must pass at least one asset when the offspring option is employed.")

    # Time window filter
    event_filters = []
    if start is not None:
        event_filters += [TimedBelief.event_start >= start]
    if end is not None:
        event_filters += [TimedBelief.event_start + Sensor.event_resolution <= end]

    # Entity filter
    entity_filters = []
    if sensors:
        entity_filters += [TimedBelief.sensor_id.in_([sensor.id for sensor in sensors])]
    if generic_assets:

        # get the offspring of all generic assets
        generic_assets_offspring = []

        for asset in generic_assets:
            generic_assets_offspring.extend(asset.offspring)
        generic_assets = list(generic_assets) + generic_assets_offspring

        entity_filters += [
            TimedBelief.sensor_id == Sensor.id,
            Sensor.generic_asset_id.in_([asset.id for asset in generic_assets]),
        ]

    # Create query
    q = select(TimedBelief).join(Sensor).where(*entity_filters, *event_filters)

    # Prompt based on count of query
    num_beliefs_up_for_deletion = db.session.scalar(select(func.count()).select_from(q))
    # repr(entity) includes the IDs, which matters for the confirmation prompt
    if sensors:
        prompt = f"Delete all {num_beliefs_up_for_deletion} beliefs on {join_words_into_a_list([repr(sensor) for sensor in sensors])}?"
    elif generic_assets:
        prompt = f"Delete all {num_beliefs_up_for_deletion} beliefs on sensors of {join_words_into_a_list([repr(asset) for asset in generic_assets])}?"
    click.confirm(prompt, abort=True)
    db.session.execute(delete(TimedBelief).where(*entity_filters, *event_filters))
    click.secho(f"Removing {num_beliefs_up_for_deletion} beliefs ...")
    db.session.commit()
    num_beliefs_after = db.session.scalar(select(func.count()).select_from(q))
    # only show the entity names for the final confirmation
    message = f"{num_beliefs_after} beliefs left on sensors "
    if sensors:
        message += f"{join_words_into_a_list([sensor.name for sensor in sensors])}"
    elif generic_assets:
        message += (
            f"of {join_words_into_a_list([asset.name for asset in generic_assets])}"
        )
    if start is not None or end is not None:
        message += " within the specified time window"
    message += "."
    done(message)


@fm_delete_data.command("unchanged-beliefs", cls=DeprecatedOptionsCommand)
@with_appcontext
@click.option(
    "--sensor",
    "--sensor-id",
    "sensor_id",
    type=int,
    cls=DeprecatedOption,
    deprecated=["--sensor-id"],
    preferred="--sensor",
    help="Delete unchanged (time series) data for a single sensor only. Follow up with the sensor's ID. ",
)
@click.option(
    "--delete-forecasts/--keep-forecasts",
    "delete_unchanged_forecasts",
    default=True,
    help="Use the --keep-forecasts flag to keep unchanged beliefs with a positive belief horizon (forecasts).",
)
@click.option(
    "--delete-measurements/--keep-measurements",
    "delete_unchanged_measurements",
    default=True,
    help="Use the --keep-measurements flag to keep beliefs with a zero or negative belief horizon (measurements, nowcasts and backcasts).",
)
def delete_unchanged_beliefs(
    sensor_id: int | None = None,
    delete_unchanged_forecasts: bool = True,
    delete_unchanged_measurements: bool = True,
):
    """Delete unchanged beliefs (i.e. updated beliefs with a later belief time, but with the same event value)."""
    q = select(TimedBelief)
    if sensor_id:
        sensor = db.session.get(Sensor, sensor_id)
        if sensor is None:
            abort(f"Failed to delete any beliefs: no sensor found with id {sensor_id}.")
        q = q.filter_by(sensor_id=sensor.id)
    num_beliefs_before = db.session.scalar(select(func.count()).select_from(q))
    unchanged_queries = []
    num_forecasts_up_for_deletion = 0
    num_measurements_up_for_deletion = 0
    if delete_unchanged_forecasts:
        q_unchanged_forecasts = query_unchanged_beliefs(
            db.session,
            TimedBelief,
            q.filter(
                TimedBelief.belief_horizon > timedelta(0),
            ),
            include_non_positive_horizons=False,
        )
        unchanged_queries.append(q_unchanged_forecasts)
        num_forecasts_up_for_deletion = db.session.scalar(
            select(func.count()).select_from(q_unchanged_forecasts)
        )
    if delete_unchanged_measurements:
        q_unchanged_measurements = query_unchanged_beliefs(
            db.session,
            TimedBelief,
            q.filter(
                TimedBelief.belief_horizon <= timedelta(0),
            ),
            include_positive_horizons=False,
        )
        unchanged_queries.append(q_unchanged_measurements)
        num_measurements_up_for_deletion = db.session.scalar(
            select(func.count()).select_from(q_unchanged_measurements)
        )

    num_beliefs_up_for_deletion = (
        num_forecasts_up_for_deletion + num_measurements_up_for_deletion
    )
    prompt = f"Delete {num_beliefs_up_for_deletion} unchanged beliefs ({num_measurements_up_for_deletion} measurements and {num_forecasts_up_for_deletion} forecasts) out of {num_beliefs_before} beliefs?"
    click.confirm(prompt, abort=True)

    beliefs_up_for_deletion = list(
        chain(*[db.session.scalars(q).all() for q in unchanged_queries])
    )
    batch_size = 10000
    for i, b in enumerate(beliefs_up_for_deletion, start=1):
        if i % batch_size == 0 or i == num_beliefs_up_for_deletion:
            click.echo(f"{i} beliefs processed ...")
        db.session.delete(b)
    click.secho(f"Removing {num_beliefs_up_for_deletion} beliefs ...")
    db.session.commit()
    num_beliefs_after = db.session.scalar(select(func.count()).select_from(q))
    done(f"{num_beliefs_after} beliefs left.")


@fm_delete_data.command("nan-beliefs", cls=DeprecatedOptionsCommand)
@with_appcontext
@click.option(
    "--sensor",
    "--sensor-id",
    "sensor_id",
    type=int,
    cls=DeprecatedOption,
    deprecated=["--sensor-id"],
    preferred="--sensor",
    help="Delete NaN time series data for a single sensor only. Follow up with the sensor's ID.",
)
def delete_nan_beliefs(sensor_id: int | None = None):
    """Delete NaN beliefs."""
    q = db.session.query(TimedBelief)
    if sensor_id is not None:
        q = q.filter(TimedBelief.sensor_id == sensor_id)
    query = q.filter(TimedBelief.event_value == float("NaN"))
    prompt = f"Delete {query.count()} NaN beliefs out of {q.count()} beliefs?"
    click.confirm(prompt, abort=True)
    query.delete()
    db.session.commit()
    done(f"Done! {q.count()} beliefs left")


@fm_delete_data.command("sensor")
@with_appcontext
@click.option(
    "--id",
    "sensors",
    type=SensorIdField(),
    required=True,
    multiple=True,
    help="Delete a sensor and its (time series) data. Follow up with the sensor's ID. "
    "This argument can be given multiple times",
)
def delete_sensor(
    sensors: list[Sensor],
):
    """Delete sensors and their (time series) data."""
    n = delete(TimedBelief).where(
        TimedBelief.sensor_id.in_(sensor.id for sensor in sensors)
    )
    statements = []
    for sensor in sensors:
        statements.append(delete(Sensor).filter_by(id=sensor.id))
    click.confirm(
        f"Delete {', '.join(sensor.__repr__() for sensor in sensors)}, along with {n} beliefs?",
        abort=True,
    )
    for statement in statements:
        db.session.execute(statement)
    db.session.commit()


app.cli.add_command(fm_delete_data)
