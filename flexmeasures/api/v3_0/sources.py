from __future__ import annotations

from flask import current_app
from flask_classful import FlaskView, route
from flask_json import as_json
from flask_security import auth_required
from marshmallow import fields, Schema, validate
from packaging.version import Version, InvalidVersion
from sqlalchemy import select, or_
from webargs.flaskparser import use_kwargs

from flexmeasures.api.common.schemas.search import SearchFilterField
from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataSource, DEFAULT_DATASOURCE_TYPES
from flexmeasures.data.queries.utils import id_prefix_filter
from flexmeasures.data.services.data_sources import (
    usable_source_filter,
    user_may_read_source,
    user_may_use_source,
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
    limit = fields.Int(
        required=False,
        validate=validate.Range(min=1),
        metadata={
            "description": "Maximum number of sources to return, the most recently created ones first."
            " Without it, every accessible source is returned."
            " Note that `only_latest` collapses the sources which this limit let through, so the response can hold fewer sources than the limit allows.",
            "example": 25,
        },
    )


def source_search_term_filter(term: str):
    """Match a search term against what identifies a source: its name, its model and its id."""
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
        limit: int | None = None,
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
            the ``type`` parameter narrows the list to one source type, such as ``forecaster``,
            and the ``limit`` parameter returns only the most recently created ones.

            The ``types`` in the response are those of every source this listing can hold,
            rather than only those of the sources this call returns,
            so that one call can both search the sources and offer the types to search by.

            **Access rules:**

            This lists the sources which are the user's to work with, which is what a source has to be to be reused.
            That is a stricter rule than the one for reading one source with ``GET /api/v3_0/sources/<id>``,
            which also covers a source that recorded data on a sensor the user may read.

            - Admins see all data sources.
            - Everyone else sees the sources of their own organisation, of any organisation they consult for,
              and the sources an automation they may read computes under.
            - A source which belongs to no organisation is not listed for that reason alone.

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
        # The listing holds the sources which are the user's to work with, rather than every source they may read:
        # it is what a client picks a source to reuse from, and reusing one is a stronger thing to be allowed than reading what it computed.
        usable_sources = usable_source_filter()

        query = select(DataSource)
        if usable_sources is not None:
            query = query.where(usable_sources)
        if type is not None:
            query = query.where(DataSource.type == type)
        if filter is not None:
            query = query.where(
                or_(*(source_search_term_filter(term) for term in filter))
            )
        # The listing is ordered so that a limited one holds the same sources each time it is asked for,
        # and so that a source which was just created is in it rather than behind the limit.
        query = query.order_by(DataSource.id.desc())
        if limit is not None:
            query = query.limit(limit)

        sources: list[DataSource] = list(db.session.scalars(query).all())

        if only_latest:
            sources = _filter_sources_to_latest(sources)

        serialized = [_serialize_source(s) for s in sources]

        # Collect any extra types present in the DB but not in the defaults.
        # These are read from every source this listing can hold, rather than from the sources returned above,
        # so that narrowing the listing does not also narrow the types a client can offer to narrow it by.
        type_query = select(DataSource.type).distinct()
        if usable_sources is not None:
            type_query = type_query.where(usable_sources)
        db_types = {
            source_type
            for source_type in db.session.scalars(type_query).all()
            if source_type
        }
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

            A source is readable when it belongs to an organisation the user may read,
            when an automation they may read computes under it,
            or when it has recorded data on a sensor they may read, so that they can ask what computed a number they see.

            The ``attributes``, which hold the configuration a data generator was set up with, are only included for the first two:
            a configuration names the sensors it runs on, which can be sensors the user cannot see at all.
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
        # A source which recorded on one of the user's sensors is theirs to read, so that they can ask what computed a number they see.
        # Its attributes are another matter: a data generator's configuration names the sensors it runs on,
        # which can be sensors of an organisation whose data the user cannot see at all, so those are kept for the sources which are theirs to work with.
        may_use = user_may_use_source(source)
        if not may_use and not user_may_read_source(source):
            return {"message": "You cannot read this data source."}, 403
        return _serialize_source(source, with_attributes=may_use), 200


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
