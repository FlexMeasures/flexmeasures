from collections.abc import Mapping

from flask import current_app
from packaging.version import InvalidVersion, Version

from flexmeasures.data.models.generic_assets import GenericAsset


def use_legacy_job_responses(asset: GenericAsset) -> bool:
    """Whether API v3 job endpoints should use legacy response behaviour.

    Production deployments configure maximum incompatible client versions keyed
    by asset attributes, which are looked up on the asset and its nearby parent
    hierarchy.

    Legacy behaviour means synchronous sensor-data ingestion, HTTP 200 from
    accepted scheduling and forecasting triggers, and HTTP 400 while polling an
    unfinished schedule.

    For QA, an assumed-version mapping can supply a version when the relevant
    asset hierarchy does not define that attribute itself.
    """
    version_limits = current_app.config.get(
        "FLEXMEASURES_LEGACY_JOB_RESPONSES_MAX_INCOMPATIBLE_CLIENT_VERSION",
        {},
    )
    if not isinstance(version_limits, Mapping):
        current_app.logger.warning(
            "Invalid FLEXMEASURES_LEGACY_JOB_RESPONSES_MAX_INCOMPATIBLE_"
            "CLIENT_VERSION %r: expected a mapping of asset attribute names to "
            "maximum incompatible client versions. Ignoring compatibility setting.",
            version_limits,
        )
        return False

    assumed_client_versions = current_app.config.get(
        "FLEXMEASURES_LEGACY_JOB_RESPONSES_ASSUME_THIS_CLIENT_VERSION", {}
    )
    if not isinstance(assumed_client_versions, Mapping):
        current_app.logger.warning(
            "Invalid FLEXMEASURES_LEGACY_JOB_RESPONSES_ASSUME_THIS_CLIENT_VERSION "
            "%r: expected a mapping of asset attribute names to assumed client "
            "versions. Ignoring QA compatibility setting.",
            assumed_client_versions,
        )
        assumed_client_versions = {}

    for version_attribute, max_version in version_limits.items():
        client_version, attribute_asset = _get_asset_attribute_from_nearby_hierarchy(
            asset, version_attribute
        )
        if client_version is None:
            client_version = assumed_client_versions.get(version_attribute)
        if client_version is None:
            continue
        try:
            if Version(str(client_version)) <= Version(str(max_version)):
                return True
        except InvalidVersion:
            version_source = (
                f"on asset {attribute_asset.id}"
                if attribute_asset is not None
                else "in the QA compatibility setting"
            )
            current_app.logger.warning(
                "Ignoring invalid client version %r or maximum incompatible "
                "version %r for attribute %r %s.",
                client_version,
                max_version,
                version_attribute,
                version_source,
            )
    return False


def _get_asset_attribute_from_nearby_hierarchy(
    asset: GenericAsset, attribute: str, max_parent_depth: int = 2
) -> tuple[object | None, GenericAsset | None]:
    current_asset = asset
    for _ in range(max_parent_depth + 1):
        # A null or empty value means the attribute is not set here, so keep looking up the hierarchy.
        # Stopping on mere key presence would let such a value on a device shadow a version set on its site.
        value = (current_asset.attributes or {}).get(attribute)
        if value:
            return value, current_asset
        if current_asset.parent_asset is None:
            break
        current_asset = current_asset.parent_asset
    return None, None
