from marshmallow import fields, validate

from flexmeasures.api.common.schemas.generic_schemas import PaginationSchema
from flexmeasures.api.common.schemas.users import AccountIdField


class AssetAPIQuerySchema(PaginationSchema):
    sort_by = fields.Str(
        required=False,
        validate=validate.OneOf(["id", "name", "owner"]),
    )
    account = AccountIdField(data_key="account_id", load_default=None)
    all_accessible = fields.Bool(data_key="all_accessible", load_default=False)
    include_public = fields.Bool(data_key="include_public", load_default=False)


class AssetPaginationSchema(PaginationSchema):
    sort_by = fields.Str(
        required=False,
        validate=validate.OneOf(["id", "name", "resolution"]),
    )
    sort_dir = fields.Str(
        required=False,
        validate=validate.OneOf(["asc", "desc"]),
    )
