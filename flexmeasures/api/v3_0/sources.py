from __future__ import annotations

from flask import current_app
from flask_classful import FlaskView, route
from flask_json import as_json
from flask_security import auth_required
from marshmallow import fields, Schema
from packaging.version import Version, InvalidVersion
from sqlalchemy import select, or_, and_
from webargs.flaskparser import use_kwargs

from flexmeasures.api.common.schemas.search import SearchFilterField
from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataSource, DEFAULT_DATASOURCE_TYPES
from flexmeasures.data.queries.utils import id_prefix_filter
from flexmeasures.data.services.data_sources import (
    get_readable_source_account_ids,
    user_may_read_source,
)

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
    filter = SearchFilterField(
        required=False,
        metadata={
            "description": "Search terms, separated by spaces, matched against the source's name, its model and its id prefix. A source matching any of the terms is returned.",
            "example": "TrainPredictPipeline",
        },
    )
    type = fields.Str(
        required=False,
        metadata={
            "description": "Only return sources of this type, such as forecaster, scheduler or reporter.",
            "example": "forecaster",
        },
    )


def source_search_term_filter(term: str):
    """Match a search term against what identifies a source: its name, its model, its description and its id."""
    filters = [
        DataSource.name.ilike(f"%{term}%"),
        DataSource.model.ilike(f"%{term}%"),
    ]
    if term.isdecimal():
        filters.append(id_prefix_filter(DataSource.id, term))
    return or_(*filters)


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
    def index(
        self,
        only_latest: bool = True,
        filter: list[str] | None = None,
        type: str | None = None,
    ):
        """List accessible data sources and defined source types.

        .. :quickref: Sources; List accessible data sources and defined source types.

        ---
        get:
          summary: List accessible data sources and defined source types.
          description: |
            Returns the list of data sources accessible to the current user and
            the defined source types.

            The ``filter`` parameter searches the sources by name, by model and by id prefix,
            and the ``type`` parameter narrows the list to one source type, such as ``forecaster``.

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
        accessible_account_ids = get_readable_source_account_ids()

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
        if type is not None:
            query = query.where(DataSource.type == type)
        if filter is not None:
            query = query.where(
                or_(*(source_search_term_filter(term) for term in filter))
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

    @route("/<int:id>", methods=["GET"])
    @as_json
    def get(self, id: int):
        """Get one data source, including its attributes.

        .. :quickref: Sources; Get one data source.

        ---
        get:
          summary: Get one data source.
          description: |
            Returns the full record of one data source, including the attributes in which
            data generators (such as forecasters, schedulers and reporters) store their
            configuration.

            The access rules are the same as for listing data sources.
          security:
            - ApiKeyAuth: []
          parameters:
            - in: path
              name: id
              required: true
              description: ID of the data source.
              schema:
                type: integer
          responses:
            200:
              description: PROCESSED
              content:
                application/json:
                  example:
                    id: 6
                    name: Seita
                    type: forecaster
                    model: TrainPredictPipeline
                    version: "1"
                    description: "Seita's TrainPredictPipeline model v1"
                    account_id: 2
                    user_id: null
                    attributes:
                      data_generator:
                        config:
                          model: CustomLGBM
            401:
              description: UNAUTHORIZED
            403:
              description: INVALID_SENDER
            404:
              description: NOT_FOUND
          tags:
            - Sources
        """
        source = db.session.get(DataSource, id)
        if source is None:
            return {"message": f"No data source found with id {id}."}, 404
        if not user_may_read_source(source):
            return {"message": "You cannot read this data source."}, 403
        return _serialize_source(source, with_attributes=True), 200


def _serialize_source(source: DataSource, with_attributes: bool = False) -> dict:
    """Serialize a DataSource to a plain dict for the API response.

    With `with_attributes`, the full record is returned, including the attributes and
    any fields that are not set (rather than leaving those out).
    """
    result = {
        "id": source.id,
        "name": source.name,
        "type": source.type,
        "description": source.description,
    }
    for field in ("model", "version", "account_id", "user_id"):
        value = getattr(source, field)
        if value is not None or with_attributes:
            result[field] = value
    if with_attributes:
        result["attributes"] = source.attributes
    return result
