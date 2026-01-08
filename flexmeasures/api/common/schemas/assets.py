from marshmallow import Schema, fields, validate

from flexmeasures.api.common.schemas.generic_schemas import PaginationSchema
from flexmeasures.api.common.schemas.users import AccountIdField
from flexmeasures.data.schemas import AssetIdField
from flexmeasures.data.schemas.generic_assets import GenericAssetSchema


default_response_fields = ["id", "name", "account_id", "generic_asset_type"]


class PipedAssetFieldListField(fields.Str):
    """
    Field that represents a list of Strings, in serialized form joined by "|".
    Each one should represent a field in the AssetAPIQuerySchema.
    """

    def _deserialize(self, values: str, attr, obj, **kwargs) -> list[str]:
        if not isinstance(values, str):
            raise validate.ValidationError(
                "Invalid input type, should be a string, separable by '|'."
            )
        parameters = values.split("|") if values else []
        non_empty_parameters = [p for p in parameters if p.strip()]
        for parameter in non_empty_parameters:
            if parameter not in GenericAssetSchema._declared_fields:
                raise validate.ValidationError(
                    f"Parameter '{parameter}' is not a valid asset field."
                )
        return non_empty_parameters

    def _serialize(self, values: list[str], attr, obj, **kwargs) -> str:
        if not values:
            return ""
        return "|".join(values)


class AssetAPIQuerySchema(PaginationSchema):
    sort_by = fields.Str(
        required=False,
        validate=validate.OneOf(["id", "name", "owner"]),
        metadata=dict(
            description="Sort results by this field.",
        ),
    )
    fields_in_response = PipedAssetFieldListField(
        data_key="fields",
        load_default=default_response_fields,
        metadata=dict(
            description="Which fields to include in response. List fields separated by '|' (pipe).",
            example="id|name|flex_model",
        ),
    )
    account = AccountIdField(
        data_key="account_id",
        load_default=None,
        metadata=dict(
            description="Select assets from a given account (requires read access to that account). Per default, the user's own account is used.",
            example=67,
        ),
    )
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
    all_accessible = fields.Bool(
        data_key="all_accessible",
        load_default=False,
        metadata=dict(
            description="Whether to list assets from all accounts that the current_user has read-access to (plus all public assets).",
            example=False,
        ),
    )
    include_public = fields.Bool(
        data_key="include_public",
        load_default=False,
        metadata=dict(
            description="Whether to include public assets. Ignored if an `account_id` is set. To fetch only public assets, use [/assets/public/](#/Assets/get_api_v3_0_assets_public) instead.",
            example=False,
        ),
    )


class PublicAssetAPISchema(Schema):
    fields_in_response = PipedAssetFieldListField(
        data_key="fields",
        load_default=default_response_fields,
        metadata=dict(
            description="Which fields to include in response. List fields separated by '|' (pipe).",
            example="id|name|sensors",
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
