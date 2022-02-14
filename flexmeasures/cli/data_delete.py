from datetime import timedelta
from itertools import chain
from typing import Optional

import click
from flask import current_app as app
from flask.cli import with_appcontext
from timely_beliefs.beliefs.queries import query_unchanged_beliefs

from flexmeasures.data import db
from flexmeasures.data.models.user import Account, AccountRole, RolesAccounts, User
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.models.time_series import Sensor, TimedBelief
from flexmeasures.data.scripts.data_gen import get_affected_classes
from flexmeasures.data.services.users import find_user_by_email, delete_user


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
    role: AccountRole = AccountRole.query.filter_by(name=name).one_or_none()
    if role is None:
        click.echo(f"Account role '{name}' does not exist.")
        raise click.Abort
    accounts = role.accounts.all()
    if len(accounts) > 0:
        click.echo(
            f"The following accounts have role '{role.name}': {','.join([a.name for a in accounts])}. Removing this role from them ..."
        )
        for account in accounts:
            account.account_roles.remove(role)
    db.session.delete(role)
    db.session.commit()
    print(f"Account role '{name}'' has been deleted.")


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
    account: Account = db.session.query(Account).get(id)
    if account is None:
        print(f"Account with ID '{id}' does not exist.")
        raise click.Abort
    if not force:
        prompt = f"Delete account '{account.name}', including generic assets, users and all their data?\n"
        users = User.query.filter(User.account_id == id).all()
        if users:
            prompt += "Affected users: " + ",".join([u.username for u in users]) + "\n"
        generic_assets = GenericAsset.query.filter(GenericAsset.account_id == id).all()
        if generic_assets:
            prompt += (
                "Affected generic assets: "
                + ",".join([ga.name for ga in generic_assets])
                + "\n"
            )
        click.confirm(prompt, abort=True)
    for user in account.users:
        print(f"Deleting user {user} (and assets & data) ...")
        delete_user(user)
    for role_account_association in RolesAccounts.query.filter_by(
        account_id=account.id
    ).all():
        role = AccountRole.query.get(role_account_association.role_id)
        print(
            f"Deleting association of account {account.name} and role {role.name} ..."
        )
        db.session.delete(role_account_association)
    for asset in account.generic_assets:
        print(f"Deleting generic asset {asset} (and sensors & beliefs) ...")
        db.session.delete(asset)
    account_name = account.name
    db.session.delete(account)
    db.session.commit()
    print(f"Account {account_name} has been deleted.")


@fm_delete_data.command("user")
@with_appcontext
@click.option("--email")
@click.option(
    "--force/--no-force", default=False, help="Skip warning about consequences."
)
def delete_user_and_data(email: str, force: bool):
    """
    Delete a user & also their assets and data.
    """
    if not force:
        # TODO: later, when assets belong to accounts, remove this.
        prompt = f"Delete user '{email}', including all their assets and data?"
        click.confirm(prompt, abort=True)
    the_user = find_user_by_email(email)
    if the_user is None:
        print(f"Could not find user with email address '{email}' ...")
        return
    delete_user(the_user)
    app.db.session.commit()


def confirm_deletion(
    structure: bool = False,
    data: bool = False,
    is_by_id: bool = False,
):
    affected_classes = get_affected_classes(structure, data)
    prompt = "This deletes all %s entries from %s.\nDo you want to continue?" % (
        " and ".join(
            ", ".join(
                [affected_class.__tablename__ for affected_class in affected_classes]
            ).rsplit(", ", 1)
        ),
        app.db.engine,
    )
    if is_by_id:
        prompt = prompt.replace(" all ", " ")
    click.confirm(prompt, abort=True)


@fm_delete_data.command("structure")
@with_appcontext
@click.option(
    "--force/--no-force", default=False, help="Skip warning about consequences."
)
def delete_structure(force):
    """
    Delete all structural (non time-series) data like assets (types),
    markets (types) and weather sensors (types) and users.

    TODO: This could in our future data model (currently in development) be replaced by
    `flexmeasures delete generic-asset-type`, `flexmeasures delete generic-asset`
    and `flexmeasures delete sensor`.
    """
    if not force:
        confirm_deletion(structure=True)
    from flexmeasures.data.scripts.data_gen import depopulate_structure

    depopulate_structure(app.db)


@fm_delete_data.command("measurements")
@with_appcontext
@click.option(
    "--sensor-id",
    type=int,
    help="Delete (time series) data for a single sensor only. Follow up with the sensor's ID.",
)
@click.option(
    "--force/--no-force", default=False, help="Skip warning about consequences."
)
def delete_measurements(
    force: bool,
    sensor_id: Optional[int] = None,
):
    """Delete measurements (ex-post beliefs, i.e. with belief_horizon <= 0)."""
    if not force:
        confirm_deletion(data=True, is_by_id=sensor_id is not None)
    from flexmeasures.data.scripts.data_gen import depopulate_measurements

    depopulate_measurements(app.db, sensor_id)


@fm_delete_data.command("prognoses")
@with_appcontext
@click.option(
    "--force/--no-force", default=False, help="Skip warning about consequences."
)
@click.option(
    "--sensor-id",
    type=int,
    help="Delete (time series) data for a single sensor only. Follow up with the sensor's ID. ",
)
def delete_prognoses(
    force: bool,
    sensor_id: Optional[int] = None,
):
    """Delete forecasts and schedules (ex-ante beliefs, i.e. with belief_horizon > 0)."""
    if not force:
        confirm_deletion(data=True, is_by_id=sensor_id is not None)
    from flexmeasures.data.scripts.data_gen import depopulate_prognoses

    depopulate_prognoses(app.db, sensor_id)


@fm_delete_data.command("unchanged-beliefs")
@with_appcontext
@click.option(
    "--sensor-id",
    type=int,
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
    sensor_id: Optional[int] = None,
    delete_unchanged_forecasts: bool = True,
    delete_unchanged_measurements: bool = True,
):
    """Delete unchanged beliefs (i.e. updated beliefs with a later belief time, but with the same event value)."""
    q = db.session.query(TimedBelief)
    if sensor_id:
        sensor = Sensor.query.filter(Sensor.id == sensor_id).one_or_none()
        if sensor is None:
            print(f"Failed to delete any beliefs: no sensor found with id {sensor_id}.")
            return
        q = q.filter(TimedBelief.sensor_id == sensor.id)
    num_beliefs_before = q.count()

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
        num_forecasts_up_for_deletion = q_unchanged_forecasts.count()
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
        num_measurements_up_for_deletion = q_unchanged_measurements.count()

    num_beliefs_up_for_deletion = (
        num_forecasts_up_for_deletion + num_measurements_up_for_deletion
    )
    prompt = f"Delete {num_beliefs_up_for_deletion} unchanged beliefs ({num_measurements_up_for_deletion} measurements and {num_forecasts_up_for_deletion} forecasts) out of {num_beliefs_before} beliefs?"
    click.confirm(prompt, abort=True)

    beliefs_up_for_deletion = list(chain(*[q.all() for q in unchanged_queries]))
    batch_size = 10000
    for i, b in enumerate(beliefs_up_for_deletion, start=1):
        if i % batch_size == 0 or i == num_beliefs_up_for_deletion:
            print(f"{i} beliefs processed ...")
        db.session.delete(b)
    print(f"Removing {num_beliefs_up_for_deletion} beliefs ...")
    db.session.commit()
    num_beliefs_after = q.count()
    print(f"Done! {num_beliefs_after} beliefs left")


@fm_delete_data.command("nan-beliefs")
@with_appcontext
@click.option(
    "--sensor-id",
    type=int,
    help="Delete NaN time series data for a single sensor only. Follow up with the sensor's ID.",
)
def delete_nan_beliefs(sensor_id: Optional[int] = None):
    """Delete NaN beliefs."""
    q = db.session.query(TimedBelief)
    if sensor_id is not None:
        q = q.filter(TimedBelief.sensor_id == sensor_id)
    query = q.filter(TimedBelief.event_value == float("NaN"))
    prompt = f"Delete {query.count()} NaN beliefs out of {q.count()} beliefs?"
    click.confirm(prompt, abort=True)
    query.delete()
    db.session.commit()
    print(f"Done! {q.count()} beliefs left")


@fm_delete_data.command("sensor")
@with_appcontext
@click.option(
    "--sensor-id",
    type=int,
    required=True,
    help="Delete a single sensor and its (time series) data. Follow up with the sensor's ID.",
)
def delete_sensor(
    sensor_id: int,
):
    """Delete a sensor and all beliefs about it."""
    sensor = Sensor.query.get(sensor_id)
    n = TimedBelief.query.filter(TimedBelief.sensor_id == sensor_id).delete()
    db.session.delete(sensor)
    click.confirm(
        f"Really delete sensor {sensor_id}, along with {n} beliefs?", abort=True
    )
    db.session.commit()


app.cli.add_command(fm_delete_data)
