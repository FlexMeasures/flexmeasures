from marshmallow import Schema, fields, validate, post_load, ValidationError
from flexmeasures.api.common.schemas.search import SearchFilterField
from flexmeasures.api.common.schemas.utils import SupportsLegacyFieldAliases
from flexmeasures.data.schemas import AwareDateTimeField, DurationField


class PaginationSchema(SupportsLegacyFieldAliases, Schema):
    legacy_field_aliases = {
        "per_page": "per-page",
        "sort_by": "sort-by",
        "sort_dir": "sort-dir",
    }

    # note: the absence of this parameter would signal to the API to not paginate (so there is no default set here)
    page = fields.Int(required=False, validate=validate.Range(min=1))
    per_page = fields.Int(
        data_key="per-page",
        required=False,
        validate=validate.Range(min=1),
        load_default=10,
    )
    filter = SearchFilterField(
        required=False,
        metadata=dict(
            description="Filter results by this keyword.",
        ),
    )
    sort_by = fields.Str(
        data_key="sort-by",
        required=False,
        metadata=dict(
            description="Sort results by this field.",
        ),
    )
    sort_dir = fields.Str(
        data_key="sort-dir",
        required=False,
        validate=validate.OneOf(["asc", "desc"]),
        metadata=dict(
            description="Sort direction for the results. Ascending ('asc') or descending ('desc').",
        ),
    )


class EventWindowSchema(SupportsLegacyFieldAliases, Schema):
    """Shared event-window fields for endpoints returning event-indexed time series or annotations.

    Accepts `start`+`end`, `start`+`duration`, or `end`+`duration`. When `duration`
    is combined with only one of `start`/`end`, the other bound is derived.
    """

    legacy_field_aliases = {
        "event_starts_after": "start",
        "event_ends_before": "end",
    }

    event_starts_after = AwareDateTimeField(
        format="iso",
        data_key="start",
        required=False,
        metadata=dict(
            description="Only include events starting after this datetime (legacy alias: `event_starts_after`). May be given alone, or paired with `duration` to derive `end`.",
            example="2025-05-01T00:00:00+02:00",
        ),
    )
    event_ends_before = AwareDateTimeField(
        format="iso",
        data_key="end",
        required=False,
        metadata=dict(
            description="Only include events ending before this datetime (legacy alias: `event_ends_before`). May be given alone, or paired with `duration` to derive `start`.",
            example="2025-05-06T00:00:00+02:00",
        ),
    )
    duration = DurationField(
        required=False,
        metadata=dict(
            description="Duration of the event window, in ISO 8601 duration format. Provide together with `start` or `end` to derive the other bound.",
            example="PT24H",
        ),
    )

    @post_load
    def derive_missing_bound(self, data, **kwargs):
        duration = data.pop("duration", None)
        if duration is None:
            return data
        has_start = "event_starts_after" in data
        has_end = "event_ends_before" in data
        if has_start and not has_end:
            data["event_ends_before"] = data["event_starts_after"] + duration
        elif has_end and not has_start:
            data["event_starts_after"] = data["event_ends_before"] - duration
        elif not has_start and not has_end:
            raise ValidationError(
                "Provide `duration` together with `start` or `end`.",
                field_name="duration",
            )
        return data


class BeliefTimeFilterSchema(SupportsLegacyFieldAliases, Schema):
    """Shared belief-time fields for endpoints returning event-indexed time series or annotations.

    `beliefs_after` is deliberately left out of the generated API docs (both Sphinx
    and the OpenAPI/Swagger spec): unlike `prior` (its upper-bound counterpart),
    it has no established canonical name elsewhere in the API, and no known caller
    needs it -- but it remains a working field for backward/internal use.
    """

    legacy_field_aliases = {
        "beliefs_after": "beliefs-after",
        "beliefs_before": "prior",
    }

    beliefs_after = AwareDateTimeField(
        format="iso",
        data_key="beliefs-after",
        required=False,
        metadata=dict(
            description="Only include beliefs recorded after this datetime (legacy alias: `beliefs_after`).",
            example="2025-05-01T00:00:00+02:00",
        ),
    )
    beliefs_before = AwareDateTimeField(
        format="iso",
        data_key="prior",
        required=False,
        metadata=dict(
            description="Only include beliefs recorded prior to this datetime (legacy alias: `beliefs_before`).",
            example="2025-05-03T00:00:00+02:00",
        ),
    )
