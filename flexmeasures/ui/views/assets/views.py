from __future__ import annotations

import json
from flask import redirect, url_for, current_app, request, session
from flask_classful import FlaskView, route
from flask_security import login_required, current_user
from webargs.flaskparser import use_kwargs
from marshmallow import ValidationError

from flexmeasures.data import db
from flexmeasures.auth.policy import check_access
from flexmeasures.auth.error_handling import unauthorized_handler
from flexmeasures.data.schemas import StartEndTimeSchema
from flexmeasures.data.services.generic_assets import (
    create_asset,
    patch_asset,
    delete_asset,
)
from flexmeasures.data.models.generic_assets import (
    GenericAsset,
    get_center_location_of_assets,
)
from flexmeasures.data.schemas.generic_assets import GenericAssetSchema as AssetSchema
from flexmeasures.ui.utils.view_utils import ICON_MAPPING
from flexmeasures.data.models.user import Account
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template
from flexmeasures.ui.views.assets.forms import NewAssetForm, AssetForm
from flexmeasures.ui.views.assets.utils import (
    get_asset_by_id_or_raise_notfound,
    user_can_create_assets,
    user_can_create_children,
    user_can_delete,
    user_can_update,
    get_list_assets_chart,
    add_child_asset,
)
from flexmeasures.data.services.sensors import (
    get_asset_sensors_metadata,
)
from flexmeasures.ui.utils.view_utils import available_units

"""
Asset crud view.
"""

asset_schema = AssetSchema()
patch_asset_schema = AssetSchema(partial=True, exclude=["account_id"])


class AssetCrudUI(FlaskView):
    """
    These views help us offer a Jinja2-based UI.
    If endpoints create/change data, we aim to use the logic and authorization in the actual API,
    so these views simply call the API functions,and deal with the response.
    """

    route_base = "/assets"
    trailing_slash = False

    @login_required
    def index(self, msg="", **kwargs):
        """GET from /assets

        List the user's assets. For admins, list across all accounts.
        """

        return render_flexmeasures_template(
            "assets/assets.html",
            asset_icon_map=ICON_MAPPING,
            message=msg,
            account=None,
            user_can_create_assets=user_can_create_assets(),
        )

    @login_required
    def owned_by(self, account_id: str):
        """GET /assets/owned_by/<account_id>"""
        msg = ""
        account: Account | None = (
            db.session.query(Account).filter_by(id=account_id).one_or_none()
        )
        if account is None:
            assets = []
            msg = f"Account {account_id} unknown."
        else:
            assets = account.generic_assets
        return render_flexmeasures_template(
            "assets/assets.html",
            asset_icon_map=ICON_MAPPING,
            account=account,
            assets=assets,
            msg=msg,
            user_can_create_assets=user_can_create_assets(),
        )

    @login_required
    def get(self, id: str, **kwargs):
        """/assets/<id>"""
        """
        This is a kind of utility view that redirects to the default asset view, either Context or the one saved in the user session.
        """
        if id == "new":  # show empty asset creation form
            parent_asset_id = request.args.get("parent_asset_id", "")
            account_id = request.args.get("account_id", "")

            asset_form = NewAssetForm()
            asset_form.with_options()
            map_center = get_center_location_of_assets(user=current_user)

            parent_asset_name = ""
            account = None
            if account_id:
                account = db.session.get(Account, account_id)
            if parent_asset_id:
                parent_asset = db.session.get(GenericAsset, parent_asset_id)
                if parent_asset:
                    parent_asset_name = parent_asset.name
                if parent_asset.owner:  # public parent asset
                    if not account_id:
                        account = parent_asset.owner
                    else:
                        if account_id != parent_asset.owner.id:
                            return (
                                f"The parent asset needs to be under the specified account ({parent_asset.owner.id}).",
                                422,
                            )
                if parent_asset.latitude and parent_asset.longitude:
                    asset_form.latitude.data = parent_asset.latitude
                    asset_form.longitude.data = parent_asset.longitude
                    map_center = parent_asset.latitude, parent_asset.longitude

            if account and not user_can_create_assets(account=account):
                return unauthorized_handler(None, [])

            if account:  # Pre-set account
                asset_form.account_id.data = str(account.id)

            return render_flexmeasures_template(
                "assets/asset_new.html",
                asset_form=asset_form,
                msg="",
                map_center=map_center,
                mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
                parent_asset_name=parent_asset_name,
                parent_asset_id=parent_asset_id,
                account=account,
            )

        # otherwise, redirect to the default asset view
        default_asset_view = session.get("default_asset_view", "Context")
        return redirect(
            url_for(
                "AssetCrudUI:{}".format(default_asset_view.replace(" ", "").lower()),
                id=id,
                **kwargs,
            )
        )

    @login_required
    @route("/<id>/context")
    def context(self, id: str, **kwargs):
        """/assets/<id>/context"""
        asset = get_asset_by_id_or_raise_notfound(id)
        check_access(asset, "read")
        assets = get_list_assets_chart(asset, base_asset=asset)
        assets = add_child_asset(asset, assets)
        current_asset_sensors = [
            {
                "name": sensor.name,
                "unit": sensor.unit,
                "link": url_for("SensorUI:get", id=sensor.id),
            }
            for sensor in asset.sensors
        ]

        site_asset = asset
        while site_asset.parent_asset_id:
            site_asset = site_asset.parent_asset

        from flexmeasures.data.schemas.scheduling import UI_FLEX_CONTEXT_SCHEMA

        return render_flexmeasures_template(
            "assets/asset_context.html",
            assets=assets,
            asset=asset,
            flex_context_schema=UI_FLEX_CONTEXT_SCHEMA,
            current_asset_sensors=current_asset_sensors,
            site_asset=site_asset,
            user_can_create_children=user_can_create_children(asset),
            mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
            current_page="Context",
            available_units=available_units(),
        )

    @login_required
    @route("/<id>/sensors/new")
    def create_sensor(self, id: str):
        """GET to /assets/<id>/sensors/new"""
        asset = get_asset_by_id_or_raise_notfound(id)
        check_access(asset, "create-children")

        return render_flexmeasures_template(
            "sensors/sensor_new.html",
            asset=asset,
            available_units=available_units(),
        )

    @login_required
    @route("/<id>/status")
    def status(self, id: str):
        """GET from /assets/<id>/status to show the staleness of the asset's sensors."""
        asset = get_asset_by_id_or_raise_notfound(id)
        check_access(asset, "read")

        status_data = get_asset_sensors_metadata(asset)

        return render_flexmeasures_template(
            "sensors/status.html",
            asset=asset,
            sensors=status_data,
            current_page="Status",
        )

    @login_required
    def post(self, id: str):  # noqa: C901
        """
        Either "create" a new asset from POST data.
        Or, if an actual ID is given, patch the existing asset with POST data.
        """
        asset: GenericAsset = None

        if id == "create":
            asset_form = NewAssetForm()
            asset_form.with_options()

            account, account_error = asset_form.set_account()
            asset_type, asset_type_error = asset_form.set_asset_type()

            check_access(account, "create-children")

            form_valid = asset_form.validate_on_submit()

            # Fill up the form with useful errors for the user
            if account_error is not None and asset_form.account_id:
                form_valid = False
                asset_form.account_id.errors.append(account_error)
            if asset_type_error is not None:
                form_valid = False
                asset_form.generic_asset_type_id.errors.append(asset_type_error)

            # Create new asset or return the form for new assets with a message
            if form_valid and asset_type is not None:
                post_args = asset_form.to_json()
                if post_args.get("account_id") == -1:
                    del post_args["account_id"]

                # do our validation here already, so we can display errors nicely
                errors = asset_schema.validate(post_args)
                if errors:
                    fields = list(asset_form._fields.keys())
                    for field in [f for f in fields if f in errors]:
                        asset_form._fields[field].errors.append(errors[field])
                    asset = None
                else:
                    loaded_data = asset_schema.load(post_args)
                    asset = create_asset(loaded_data)
                    db.session.commit()
                    session["msg"] = "Creation was successful."
            if asset is None:
                if asset_form.latitude.data and asset_form.longitude.data:
                    map_center = asset_form.latitude.data, asset_form.longitude.data
                else:
                    map_center = get_center_location_of_assets(user=current_user)
                return render_flexmeasures_template(
                    "assets/asset_new.html",
                    asset_form=asset_form,
                    msg="Cannot create asset.",
                    parent_asset_id=asset_form.parent_asset_id.data or "",
                    map_center=map_center,
                    mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
                )

        else:
            asset = get_asset_by_id_or_raise_notfound(id)
            check_access(asset, "update")
            asset_form = AssetForm()
            asset_form.with_options()
            if not asset_form.validate_on_submit():
                session["msg"] = f"Cannot edit asset: {asset_form.errors}"
                return redirect(url_for("AssetCrudUI:properties", id=id))
            try:
                loaded_asset_data = patch_asset_schema.load(asset_form.to_json())
                patch_asset(asset, loaded_asset_data)
                db.session.commit()
                session["msg"] = "Editing was successful."
            except ValidationError as ve:
                # we are redirecting to the properties page, there we cannot show errors in form
                session["msg"] = f"Cannot edit asset: {ve.messages}"
            except Exception as exc:
                session["msg"] = "Cannot edit asset: An error occurred."
                current_app.logger.error(exc)

        return redirect(url_for("AssetCrudUI:properties", id=asset.id))

    @login_required
    def delete_with_data(self, id: str):
        """Delete via /assets/delete_with_data/<id>"""
        asset = get_asset_by_id_or_raise_notfound(id)
        delete_asset(asset)
        db.session.commit()
        return self.index(
            msg=f"Asset {id} and assorted meter readings / forecasts have been deleted."
        )

    @login_required
    @route("/<id>/auditlog")
    def auditlog(self, id: str):
        """/assets/<id>/auditlog"""
        asset = get_asset_by_id_or_raise_notfound(id)
        check_access(asset, "read")

        return render_flexmeasures_template(
            "assets/asset_audit_log.html",
            asset=asset,
            current_page="Audit Log",
        )

    @login_required
    @use_kwargs(StartEndTimeSchema, location="query")
    @route("/<id>/graphs")
    def graphs(self, id: str, start_time=None, end_time=None):
        """/assets/<id>/graphs"""
        asset = get_asset_by_id_or_raise_notfound(id)
        check_access(asset, "read")
        asset_kpis = asset.sensors_to_show_as_kpis

        has_kpis = False
        if len(asset_kpis) > 0:
            has_kpis = True

        asset_form = AssetForm()
        asset_form.with_options()
        asset_form.process(obj=asset)

        return render_flexmeasures_template(
            "assets/asset_graph.html",
            asset=asset,
            has_kpis=has_kpis,
            asset_kpis=asset_kpis,
            current_page="Graphs",
        )

    @login_required
    @route("/<id>/properties")
    def properties(self, id: str):
        """/assets/<id>/properties"""
        # Extract the message from session
        if session.get("msg"):
            msg = session["msg"]
            session.pop("msg")
        else:
            msg = ""

        asset = get_asset_by_id_or_raise_notfound(id)
        check_access(asset, "read")

        asset_form = AssetForm()
        asset_form.with_options()
        asset_form.process(obj=asset)

        # JSON fields need to be pre-processed to be valid form data
        asset_form.attributes.data = json.dumps(asset.attributes)
        asset_form.sensors_to_show_as_kpis.data = json.dumps(
            asset.sensors_to_show_as_kpis
        )

        asset_summary = {
            "Name": asset.name,
            "Latitude": asset.latitude,
            "Longitude": asset.longitude,
            "Parent Asset": (
                f"{asset.parent_asset.name} ({asset.parent_asset.generic_asset_type.name})"
                if asset.parent_asset
                else "No Parent"
            ),
        }

        site_asset = asset
        while site_asset.parent_asset_id:
            site_asset = site_asset.parent_asset

        return render_flexmeasures_template(
            "assets/asset_properties.html",
            asset=asset,
            site_asset=site_asset,
            asset_flexmodel=json.dumps(asset.flex_model),
            available_units=available_units(),
            asset_summary=asset_summary,
            asset_form=asset_form,
            msg=msg,
            mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
            user_can_create_assets=user_can_create_assets(),
            user_can_create_children=user_can_create_children(asset),
            user_can_delete_asset=user_can_delete(asset),
            user_can_update_asset=user_can_update(asset),
            current_page="Properties",
        )
