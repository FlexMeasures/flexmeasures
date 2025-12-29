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
        data_key="root",
        load_default=None,
        metadata=dict(
            description="Select all descendants of a given root asset (including the root itself). Leave out to include top-level assets.",
            example=482,
        ),
    )
    max_depth = fields.Int(
        data_key="depth",
        validate=validate.Range(min=0),
        load_default=None,
        metadata=dict(
            description="Maximum number of levels of descendant assets to include. Set to 0 to include root assets only. Leave out to include the whole tree.",
            example=2,
        ),
    )
    all_accessible = fields.Bool(data_key="all_accessible", load_default=False)
    include_public = fields.Bool(
        data_key="include_public",
        load_default=False,
        metadata=dict(
            description="Whether to include public assets. Ignored if an `account_id` is set. To fetch only public assets, use [/assets/public/](#/Assets/get_api_v3_0_assets_public) instead.",
            example=False,
        ),
    )


class AssetPaginationSchema(PaginationSchema):
    sort_by = fields.Str(
        required=False,
        validate=validate.OneOf(["id", "name", "resolution"]),
    )
    sort_dir = fields.Str(
        required=False,
        validate=validate.OneOf(["asc", "desc"]),
    )
