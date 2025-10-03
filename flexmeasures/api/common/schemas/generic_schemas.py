from marshmallow import Schema, fields, validate
from flexmeasures.api.common.schemas.search import SearchFilterField


class PaginationSchema(Schema):
    page = fields.Int(required=False, validate=validate.Range(min=1))
    per_page = fields.Int(
        required=False, validate=validate.Range(min=1), load_default=1
    )
    filter = SearchFilterField(required=False)
    sort_by = fields.Str(
        required=False,
    )
    sort_dir = fields.Str(required=False, validate=validate.OneOf(["asc", "desc"]))
