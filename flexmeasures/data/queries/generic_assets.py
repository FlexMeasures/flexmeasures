from typing import List, Union

from sqlalchemy.orm import Query

from flexmeasures.data.models.generic_assets import GenericAsset, GenericAssetType


def query_assets_by_type(type_names: Union[List[str], str]) -> Query:
    """
    Return a query which looks for GenericAssets by their type.
    Pass in a list of type names or only one type name.
    """
    query = GenericAsset.query.join(GenericAssetType).filter(
        GenericAsset.generic_asset_type_id == GenericAssetType.id
    )
    if isinstance(type_names, str):
        query = query.filter(GenericAssetType.name == type_names)
    else:
        query = query.filter(GenericAssetType.name.in_(type_names))
    return query
