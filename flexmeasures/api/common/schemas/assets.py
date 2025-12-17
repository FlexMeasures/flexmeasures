from marshmallow import fields, validate

from flexmeasures.api.common.schemas.generic_schemas import PaginationSchema
from flexmeasures.api.common.schemas.users import AccountIdField
from flexmeasures.data.schemas import AssetIdField


class AssetAPIQuerySchema(PaginationSchema):
    sort_by = fields.Str(
        required=False,
        validate=validate.OneOf(["id", "name", "owner"]),
    )
    account = AccountIdField(data_key="account_id", load_default=None)
    root_asset = AssetIdField(
        data_key="asset",
        load_default=None,
        metadata=dict(
            description="Select all descendants of a given root asset (including the root itself)."
        ),
    )
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
