from __future__ import annotations

import json
from timely_beliefs.beliefs.classes import BeliefsDataFrame
from typing import Sequence
from datetime import timedelta

from flask import current_app
from werkzeug.exceptions import Forbidden, Unauthorized
from numpy import array
from psycopg2.errors import UniqueViolation
from rq.job import Job, JobStatus, NoSuchJobError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from flexmeasures.data import db
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.generic_assets import GenericAsset
from flexmeasures.data.utils import save_to_db
from flexmeasures.auth.policy import check_access
from flexmeasures.api.common.responses import (
    invalid_replacement,
    ResponseTuple,
    request_processed,
    already_received_and_successfully_processed,
)
from flexmeasures.data.schemas.generic_assets import GenericAssetSchema as AssetSchema
from flexmeasures.utils.error_utils import error_handling_router
from flexmeasures.utils.flexmeasures_inflection import capitalize


def upsample_values(
    value_groups: list[list[float]] | list[float],
    from_resolution: timedelta,
    to_resolution: timedelta,
) -> list[list[float]] | list[float]:
    """Upsample the values (in value groups) to a smaller resolution.
    from_resolution has to be a multiple of to_resolution"""
    if from_resolution % to_resolution == timedelta(hours=0):
        n = from_resolution // to_resolution
        if isinstance(value_groups[0], list):
            value_groups = [
                list(array(value_group).repeat(n)) for value_group in value_groups
            ]
        else:
            value_groups = list(array(value_groups).repeat(n))
    return value_groups


def unique_ever_seen(iterable: Sequence, selector: Sequence):
    """
    Return unique iterable elements with corresponding lists of selector elements, preserving order.

    >>> a, b = unique_ever_seen([[10, 20], [10, 20], [20, 40]], [1, 2, 3])
    >>> print(a)
    [[10, 20], [20, 40]]
    >>> print(b)
    [[1, 2], 3]
    """
    u = []
    s = []
    for iterable_element, selector_element in zip(iterable, selector):
        if iterable_element not in u:
            u.append(iterable_element)
            s.append(selector_element)
        else:
            us = s[u.index(iterable_element)]
            if not isinstance(us, list):
                us = [us]
            us.append(selector_element)
            s[u.index(iterable_element)] = us
    return u, s


def job_status_description(job: Job, extra_message: str | None = None):
    """Return a matching description for the job's status.

    Supports each rq.job.JobStatus (NB JobStatus.CREATED is deprecated).

    :param job:             The rq.Job.
    :param extra_message:   Optionally, append a message to the job status description.
    """

    job_status = job.get_status()
    queue_name = job.origin  # Name of the queue that the job is in
    if job_status == JobStatus.QUEUED:
        description = f"{capitalize(queue_name)} job waiting to be processed."
    elif job_status == JobStatus.FINISHED:
        description = f"{capitalize(queue_name)} job has finished."
    elif job_status == JobStatus.FAILED:
        # Try to inform the user on why the job failed
        e = job.meta.get(
            "exception",
            Exception(
                "The job does not state why it failed. "
                "The worker may be missing an exception handler, "
                "or its exception handler is not storing the exception as job meta data."
            ),
        )
        description = (
            f"{capitalize(queue_name)} job failed with {type(e).__name__}: {e}."
        )
    elif job_status == JobStatus.STARTED:
        description = f"{capitalize(queue_name)} job in progress."
    elif job_status == JobStatus.DEFERRED:
        # Try to inform the user on what other job the job is waiting for
        try:
            preferred_job = job.dependency
            description = f'{capitalize(queue_name)} job waiting for {preferred_job.status} job "{preferred_job.id}" to be processed.'
        except NoSuchJobError:
            description = (
                f"{capitalize(queue_name)} job waiting for unknown job to be processed."
            )
    elif job_status == JobStatus.SCHEDULED:
        description = (
            f"{capitalize(queue_name)} job is scheduled to run at a later time."
        )
    elif job_status == JobStatus.STOPPED:
        description = f"{capitalize(queue_name)} job has been stopped."
    elif job_status == JobStatus.CANCELED:
        description = f"{capitalize(queue_name)} job has been cancelled."
    else:
        description = f"{capitalize(queue_name)} job has an unknown status."

    return description + f" {extra_message}" if extra_message else description


def enqueue_forecasting_jobs(
    forecasting_jobs: list[Job] | None = None,
):
    """Enqueue forecasting jobs.

    :param forecasting_jobs: list of forecasting Jobs for redis queues.
    """
    if forecasting_jobs is not None:
        [current_app.queues["forecasting"].enqueue_job(job) for job in forecasting_jobs]


def save_and_enqueue(
    data: BeliefsDataFrame | list[BeliefsDataFrame],
    forecasting_jobs: list[Job] | None = None,
    save_changed_beliefs_only: bool = True,
) -> ResponseTuple:
    # Attempt to save
    status = save_to_db(data, save_changed_beliefs_only=save_changed_beliefs_only)
    db.session.commit()

    # Only enqueue forecasting jobs upon successfully saving new data
    if status[:7] == "success" and status != "success_but_nothing_new":
        enqueue_forecasting_jobs(forecasting_jobs)

    # Pick a response
    if status == "success":
        return request_processed()
    elif status in (
        "success_with_unchanged_beliefs_skipped",
        "success_but_nothing_new",
    ):
        return already_received_and_successfully_processed()
    return invalid_replacement()


def catch_timed_belief_replacements(error: IntegrityError):
    """Catch IntegrityErrors due to a UniqueViolation on the TimedBelief primary key.

    Return a more informative message.
    """
    if isinstance(error.orig, UniqueViolation) and "timed_belief_pkey" in str(
        error.orig
    ):
        # Some beliefs represented replacements, which was forbidden
        return invalid_replacement()

    # Forward to our generic error handler
    return error_handling_router(error)


def get_accessible_accounts() -> list[Account]:
    accounts = []
    for _account in db.session.scalars(select(Account)).all():
        try:
            check_access(_account, "read")
            accounts.append(_account)
        except (Forbidden, Unauthorized):
            pass

    return accounts


def convert_asset_json_fields(asset_kwargs):
    """
    Convert string fields in asset_kwargs to JSON where needed.
    """
    if "attributes" in asset_kwargs and isinstance(asset_kwargs["attributes"], str):
        asset_kwargs["attributes"] = json.loads(asset_kwargs["attributes"])
    if "sensors_to_show" in asset_kwargs and isinstance(
        asset_kwargs["sensors_to_show"], str
    ):
        asset_kwargs["sensors_to_show"] = json.loads(asset_kwargs["sensors_to_show"])
    if "flex_context" in asset_kwargs and isinstance(asset_kwargs["flex_context"], str):
        asset_kwargs["flex_context"] = json.loads(asset_kwargs["flex_context"])
    if "flex_model" in asset_kwargs and isinstance(asset_kwargs["flex_model"], str):
        asset_kwargs["flex_model"] = json.loads(asset_kwargs["flex_model"])
    if "sensors_to_show_as_kpis" in asset_kwargs and isinstance(
        asset_kwargs["sensors_to_show_as_kpis"], str
    ):
        asset_kwargs["sensors_to_show_as_kpis"] = json.loads(
            asset_kwargs["sensors_to_show_as_kpis"]
        )
    return asset_kwargs


def fetch_and_copy_all_assets_in_account(
    account_id: int, target_account_id: int
) -> list[GenericAsset]:
    try:
        asset_schema = AssetSchema()

        # order from oldest to newest to help with parent/child dependencies
        assets = db.session.scalars(
            select(GenericAsset)
            .filter(GenericAsset.account_id == account_id)
            .order_by(GenericAsset.id)
        ).all()

        if len(assets) == 0:
            raise ValueError(f"No assets found for account {account_id}.")

        asset_mapping = {}
        parent_mapping = {}
        new_assets = []

        for old_asset in assets:
            asset_kwargs = asset_schema.dump(old_asset)

            # Remove dump_only and read-only fields
            for key in ["id", "owner", "generic_asset_type", "child_assets", "sensors"]:
                asset_kwargs.pop(key, None)

            # Avoid name collisions
            asset_kwargs["name"] = f"{asset_kwargs['name']} (Copy)"
            # Assign to the target account
            asset_kwargs["account_id"] = target_account_id
            asset_kwargs = convert_asset_json_fields(asset_kwargs)

            # Keep track of parent_asset_id to reconnect later
            if asset_kwargs.get("parent_asset_id"):
                parent_mapping[old_asset.id] = asset_kwargs["parent_asset_id"]
            asset_kwargs["parent_asset_id"] = None

            new_asset = GenericAsset(**asset_kwargs)
            db.session.add(new_asset)
            db.session.flush()

            asset_mapping[old_asset.id] = new_asset
            new_assets.append(new_asset)

        # Second loop to set the proper parent
        for old_id, old_parent_id in parent_mapping.items():
            if old_parent_id in asset_mapping:
                asset_mapping[old_id].parent_asset_id = asset_mapping[old_parent_id].id

        db.session.commit()
        return new_assets
    except Exception as e:
        db.session.rollback()
        raise e
