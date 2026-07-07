from __future__ import annotations

from flask import current_app
from flask_classful import FlaskView, route
from flask_json import as_json
from flask_security import current_user, auth_required
from marshmallow import fields, Schema
from packaging.version import Version, InvalidVersion
from sqlalchemy import select, or_, and_
from webargs.flaskparser import use_kwargs

from flexmeasures.auth.policy import user_has_admin_access, CONSULTANT_ROLE
from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataSource, DEFAULT_DATASOURCE_TYPES

"""
API endpoint to list accessible data sources and defined source types.
"""


class SourceQuerySchema(Schema):
    only_latest = fields.Bool(
        load_default=True,
        metadata={
            "description": (
                "If true, return only the most recent version of each source "
                "(grouped by name, type and model). Defaults to true. "
                "Determined by the highest model version string; ties are "
                "broken by the highest source id."
            )
        },
    )


def _get_accessible_account_ids() -> list[int] | None:
    """Return account IDs whose sources the current user may read.

    Returns None to indicate "all accounts" (admin access).
    """
    if user_has_admin_access(current_user, "read"):
        return None  # all sources

    accessible_ids = [current_user.account_id]
    if current_user.has_role(CONSULTANT_ROLE):
        for client_account in current_user.account.consultancy_client_accounts:
            accessible_ids.append(client_account.id)
    return accessible_ids


def _filter_sources_to_latest(sources: list[DataSource]) -> list[DataSource]:
    """Keep only the highest-versioned DataSource per (name, type, model, account_id) group.

    ``account_id`` is included in the key so that two sources with the same
    generator identity but belonging to different organisations are never
    collapsed into one — both represent valid, distinct lineages.

    When two sources share the same version (or both have no version), the one
    with the higher id wins.
    """

    def _version_key(source: DataSource):
        try:
            return Version(source.version or "0.0.0")
        except InvalidVersion:
            current_app.logger.warning(
                "DataSource %d has an invalid version string %r; treating as 0.0.0",
                source.id,
                source.version,
            )
            return Version("0.0.0")

    best: dict[tuple[str, str, str | None, int | None], DataSource] = {}
    for source in sources:
        key = (source.name, source.type, source.model, source.account_id)
        if key not in best:
            best[key] = source
        else:
            existing = best[key]
            if (_version_key(source), source.id) > (
                _version_key(existing),
                existing.id,
            ):
                best[key] = source
    return list(best.values())


class SourceAPI(FlaskView):
    route_base = "/sources"
    trailing_slash = False
    decorators = [auth_required()]

    @route("", methods=["GET"])
    @use_kwargs(SourceQuerySchema, location="query")
    @as_json
    def index(self, only_latest: bool = True):
        """List accessible data sources and defined source types.

        .. :quickref: Sources; List accessible data sources and defined source types.

        ---
        get:
          summary: List accessible data sources and defined source types.
          description: |
            Returns the list of data sources accessible to the current user and
            the defined source types.

            **Access rules:**

            - Admins see all data sources.
            - Users with the ``consultant`` role see sources belonging to their
              own account and to any consultancy-client accounts for which their
              account is the consultancy.
            - All other authenticated users see only sources belonging to their
              own account, plus sources that have neither a ``user_id`` nor an
              ``account_id`` (i.e. system/public sources).

          security:
            - ApiKeyAuth: []
          parameters:
            - in: query
              schema: SourceQuerySchema
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  example:
                    types:
                      - user
                      - scheduler
                      - forecaster
                      - reporter
                      - demo script
                      - gateway
                      - market
                    sources:
                      - id: 1
                        name: Seita
                        type: scheduler
                        model: StorageScheduler
                        version: "1.0"
                        description: "Seita's StorageScheduler model v1.0"
                        account_id: 2
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
          tags:
            - Sources
        """
        accessible_account_ids = _get_accessible_account_ids()

        query = select(DataSource)
        if accessible_account_ids is not None:
            # Sources owned by one of the accessible accounts, OR sources
            # with no account_id AND no user_id (system / public sources).
            query = query.where(
                or_(
                    DataSource.account_id.in_(accessible_account_ids),
                    and_(
                        DataSource.account_id.is_(None),
                        DataSource.user_id.is_(None),
                    ),
                )
            )

        sources: list[DataSource] = list(db.session.scalars(query).all())

        if only_latest:
            sources = _filter_sources_to_latest(sources)

        serialized = [_serialize_source(s) for s in sources]

        # Collect any extra types present in the DB but not in the defaults
        db_types = {s.type for s in sources if s.type}
        all_types = list(DEFAULT_DATASOURCE_TYPES) + sorted(
            db_types - set(DEFAULT_DATASOURCE_TYPES)
        )

        return {"types": all_types, "sources": serialized}, 200


def _serialize_source(source: DataSource) -> dict:
    """Serialize a DataSource to a plain dict for the API response."""
    result = {
        "id": source.id,
        "name": source.name,
        "type": source.type,
        "description": source.description,
    }
    if source.model is not None:
        result["model"] = source.model
    if source.version is not None:
        result["version"] = source.version
    if source.account_id is not None:
        result["account_id"] = source.account_id
    if source.user_id is not None:
        result["user_id"] = source.user_id
    return result
