"""
Endpoints that store a user's choices in the FlexMeasures UI in their session.
"""

from flask import session
from flask_classful import FlaskView, route
from flask_json import as_json
from flask_security import auth_required
from marshmallow import Schema, fields, validate
from webargs.flaskparser import use_kwargs

from flexmeasures.ui.utils.view_utils import clear_session

ASSET_VIEWS = ["Audit Log", "Context", "Graphs", "Properties", "Status"]
STATUS_PAGE_TABS = ["jobs", "sensors"]


class DefaultAssetViewSchema(Schema):
    default_asset_view = fields.Str(
        data_key="default-asset-view",
        required=False,
        validate=validate.OneOf(ASSET_VIEWS),
    )
    use_as_default = fields.Bool(data_key="use-as-default", load_default=True)


class KeepLegendsBelowGraphsSchema(Schema):
    keep_legends_below_graphs = fields.Bool(
        data_key="keep-legends-below-graphs", load_default=True
    )


class StatusPageTabSchema(Schema):
    status_page_tab = fields.Str(
        data_key="status-page-tab",
        required=True,
        validate=validate.OneOf(STATUS_PAGE_TABS),
    )


class IncludeChildAssetsSchema(Schema):
    # A page lists what happens below the asset, too, unless the user switches that off (see #2447).
    include_child_assets = fields.Bool(
        data_key="include-child-assets", load_default=True
    )


class SessionAPI(FlaskView):
    """
    These endpoints store the current user's choices in the FlexMeasures UI in their session,
    such as which asset view to open, so that the UI keeps to them on the user's next visit.

    Like the other endpoints of this blueprint, they are not part of the official API.
    They exist to support the FlexMeasures UI, and may change or disappear in any FlexMeasures version.
    """

    route_base = "/session"
    trailing_slash = False
    decorators = [auth_required()]

    @route("/default-asset-view", methods=["POST"])
    @use_kwargs(DefaultAssetViewSchema, location="json")
    @as_json
    def update_default_asset_view(
        self, use_as_default: bool = True, default_asset_view: str | None = None
    ):
        """Set which asset view the current user sees first when opening an asset, or go back to the system default."""
        if use_as_default and default_asset_view is not None:
            session["default_asset_view"] = default_asset_view
        elif not use_as_default:
            clear_session(keys_to_clear=["default_asset_view"])
        return {"message": "Default asset view updated successfully."}, 200

    @route("/keep-legends-below-graphs", methods=["POST"])
    @use_kwargs(KeepLegendsBelowGraphsSchema, location="json")
    @as_json
    def update_keep_legends_below_graphs(self, keep_legends_below_graphs: bool = True):
        """Set whether the current user's charts keep their legends below the graphs, even for many sensors."""
        if keep_legends_below_graphs:
            session["keep_legends_below_graphs"] = True
        else:
            clear_session(keys_to_clear=["keep_legends_below_graphs"])
        return {"message": "Legend position preference updated successfully."}, 200

    @route("/status-page-tab", methods=["POST"])
    @use_kwargs(StatusPageTabSchema, location="json")
    @as_json
    def update_status_page_tab(self, status_page_tab: str):
        """Remember which tab of the asset status page the current user last opened."""
        session["status_page_tab"] = status_page_tab
        return {"message": "Preferred status page tab updated successfully."}, 200

    @route("/status-page-child-jobs", methods=["POST"])
    @use_kwargs(IncludeChildAssetsSchema, location="json")
    @as_json
    def update_status_page_child_jobs(self, include_child_assets: bool = True):
        """Remember whether the current user wants the asset status page to list the jobs of the assets below it, too."""
        session["status_page_include_child_assets"] = include_child_assets
        return {"message": "Preferred status page job scope updated successfully."}, 200

    @route("/automations-page-child-assets", methods=["POST"])
    @use_kwargs(IncludeChildAssetsSchema, location="json")
    @as_json
    def update_automations_page_child_assets(self, include_child_assets: bool = True):
        """Remember whether the current user wants the asset automations page to list the automations of the assets below it, too."""
        session["automations_page_include_child_assets"] = include_child_assets
        return {
            "message": "Preferred automations page scope updated successfully."
        }, 200
