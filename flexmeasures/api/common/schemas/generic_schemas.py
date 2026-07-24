from marshmallow import Schema, fields, validate
from flexmeasures.api.common.schemas.search import SearchFilterField
from flexmeasures.api.common.schemas.utils import SupportsLegacyFieldAliases


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
