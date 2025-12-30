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
        for parameter in parameters:
            if parameter not in GenericAssetSchema._declared_fields:
                raise validate.ValidationError(
                    f"Parameter '{parameter}' is not a valid asset field."
                )
        return parameters

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
    account = AccountIdField(
        data_key="account_id",
        load_default=None,
        metadata=dict(
            description="Filter results by this account.",
        ),
    )
    root_asset = AssetIdField(
        data_key="root",
        load_default=None,
        metadata=dict(
            description="Select all descendants of a given root asset (including the root itself). Leave out to select top-level assets.",
            example=482,
        ),
    )
    max_depth = fields.Int(
        data_key="depth",
        validate=validate.Range(min=0),
        load_default=None,
        metadata=dict(
            description="Maximum number of levels of descendant assets to include. Set to 0 to include root assets only.",
            example=2,
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
    all_accessible = fields.Bool(data_key="all_accessible", load_default=False)
    include_public = fields.Bool(data_key="include_public", load_default=False)


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
