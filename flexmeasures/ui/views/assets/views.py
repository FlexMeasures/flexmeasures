from __future__ import annotations

from flask import redirect, url_for, current_app, request, session
from flask_classful import FlaskView, route
from flask_security import login_required, current_user
from werkzeug.exceptions import NotFound
from webargs.flaskparser import use_kwargs
from flexmeasures.auth.error_handling import unauthorized_handler

from flexmeasures.data import db
from flexmeasures.auth.policy import check_access
from flexmeasures.data.schemas import StartEndTimeSchema
from flexmeasures.data.models.generic_assets import (
    GenericAsset,
    get_center_location_of_assets,
)
from flexmeasures.ui.utils.view_utils import ICON_MAPPING
from flexmeasures.data.models.user import Account
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template
from flexmeasures.ui.views.api_wrapper import InternalApi
from flexmeasures.ui.views.assets.forms import NewAssetForm, AssetForm
from flexmeasures.ui.views.assets.utils import (
    process_internal_api_response,
    user_can_create_assets,
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

Note: This uses the internal dev API version
      ― if those endpoints get moved or updated to a higher version,
      we probably should change the version used here, as well.
"""


class AssetCrudUI(FlaskView):
    """
    These views help us offer a Jinja2-based UI.
    The main focus on logic is the API, so these views simply call the API functions,
    and deal with the response.
    Some new functionality, like fetching accounts and asset types, is added here.
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
        """/assets/owned_by/<account_id>"""
        msg = ""
        get_assets_response = InternalApi().get(
            url_for("AssetAPI:index"),
            query={"account_id": account_id},
            do_not_raise_for=[404],
        )
        if get_assets_response.status_code == 404:
            assets = []
            msg = f"Account {account_id} unknown."
        else:
            assets = [
                process_internal_api_response(ad, make_obj=True)
                for ad in get_assets_response.json()
            ]
        db.session.flush()
        return render_flexmeasures_template(
            "assets/assets.html",
            account=db.session.get(Account, account_id),
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
        # Get default asset view
        parent_asset_id = request.args.get("parent_asset_id", "")
        if id == "new":
            if not user_can_create_assets():
                return unauthorized_handler(None, [])

            asset_form = NewAssetForm()
            asset_form.with_options()
            parent_asset_name = ""
            account = None
            if parent_asset_id:
                parent_asset = db.session.get(GenericAsset, parent_asset_id)
                if parent_asset:
                    asset_form.account_id.data = str(
                        parent_asset.account_id
                    )  # Pre-set account
                    parent_asset_name = parent_asset.name
                    account = parent_asset.account_id
            return render_flexmeasures_template(
                "assets/asset_new.html",
                asset_form=asset_form,
                msg="",
                map_center=get_center_location_of_assets(user=current_user),
                mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
                parent_asset_name=parent_asset_name,
                parent_asset_id=parent_asset_id,
                account=account,
            )

        asset = db.session.query(GenericAsset).filter_by(id=id).first()
        if asset is None:
            assets = []
        else:
            assets = get_list_assets_chart(asset, base_asset=asset)

        current_asset_sensors = [
            {
                "name": sensor.name,
                "unit": sensor.unit,
                "link": url_for("SensorUI:get", id=sensor.id),
            }
            for sensor in asset.sensors
        ]
        assets = add_child_asset(asset, assets)

        return render_flexmeasures_template(
            "assets/asset_context.html",
            assets=assets,
            asset=asset,
            current_asset_sensors=current_asset_sensors,
            mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
            current_page="Context",
            available_units=available_units(),
        )

    @login_required
    @route("/<id>/sensor/new")
    def create_sensor(self, id: str):
        """GET to /assets/<id>/sensor/new"""
        asset = GenericAsset.query.get(id)
        if asset is None:
            raise NotFound
        check_access(asset, "create-children")

        return render_flexmeasures_template(
            "assets/sensor_new.html",
            asset=asset,
            available_units=available_units(),
        )

    @login_required
    @route("/<id>/status")
    def status(self, id: str):
        """GET from /assets/<id>/status to show the staleness of the asset's sensors."""

        asset = GenericAsset.query.get(id)
        if asset is None:
            raise NotFound
        check_access(asset, "read")

        status_data = get_asset_sensors_metadata(asset)

        return render_flexmeasures_template(
            "sensors/status.html",
            asset=asset,
            sensors=status_data,
            current_page="Status",
        )

    @login_required
    def post(self, id: str):
        """POST to /assets/<id>, where id can be 'create' (and thus a new asset is made from POST data)
        Most of the code deals with creating a user for the asset if no existing is chosen.
        """

        asset: GenericAsset = None
        error_msg = ""

        if id == "create":
            asset_form = NewAssetForm()
            asset_form.with_options()

            account, account_error = asset_form.set_account()
            asset_type, asset_type_error = asset_form.set_asset_type()

            form_valid = asset_form.validate_on_submit()

            # Fill up the form with useful errors for the user
            if account_error is not None:
                form_valid = False
                asset_form.account_id.errors.append(account_error)
            if asset_type_error is not None:
                form_valid = False
                asset_form.generic_asset_type_id.errors.append(asset_type_error)

            # Create new asset or return the form for new assets with a message
            if form_valid and asset_type is not None:
                post_asset_response = InternalApi().post(
                    url_for("AssetAPI:post"),
                    args=asset_form.to_json(),
                    do_not_raise_for=[400, 422],
                )
                if post_asset_response.status_code in (200, 201):
                    asset_dict = post_asset_response.json()
                    asset = process_internal_api_response(
                        asset_dict, int(asset_dict["id"]), make_obj=True
                    )
                    msg = "Creation was successful."
                else:
                    current_app.logger.error(
                        f"Internal asset API call unsuccessful [{post_asset_response.status_code}]: {post_asset_response.text}"
                    )
                    asset_form.process_api_validation_errors(post_asset_response.json())
                    if "message" in post_asset_response.json():
                        asset_form.process_api_validation_errors(
                            post_asset_response.json()["message"]
                        )
                        if "json" in post_asset_response.json()["message"]:
                            error_msg = str(
                                post_asset_response.json()["message"]["json"]
                            )
            if asset is None:
                msg = "Cannot create asset. " + error_msg
                return render_flexmeasures_template(
                    "assets/asset_new.html",
                    asset_form=asset_form,
                    msg=msg,
                    map_center=get_center_location_of_assets(user=current_user),
                    mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
                )

        else:
            asset = db.session.get(GenericAsset, id)
            asset_form = AssetForm()
            asset_form.with_options()
            if not asset_form.validate_on_submit():
                # Display the form data, but set some extra data which the page wants to show.
                asset_info = asset_form.to_json()
                asset_info = {
                    k: v for k, v in asset_info.items() if k not in asset_form.errors
                }
                asset_info["id"] = id
                asset_info["account_id"] = asset.account_id
                asset = process_internal_api_response(
                    asset_info, int(id), make_obj=True
                )
                session["msg"] = "Cannot edit asset."
                return redirect(url_for("AssetCrudUI:properties", id=asset.id))
            patch_asset_response = InternalApi().patch(
                url_for("AssetAPI:patch", id=id),
                args=asset_form.to_json(),
                do_not_raise_for=[400, 422],
            )
            asset_dict = patch_asset_response.json()
            if patch_asset_response.status_code in (200, 201):
                asset = process_internal_api_response(
                    asset_dict, int(id), make_obj=True
                )
                msg = "Editing was successful."
            else:
                current_app.logger.error(
                    f"Internal asset API call unsuccessful [{patch_asset_response.status_code}]: {patch_asset_response.text}"
                )
                msg = "Cannot edit asset."
                asset_form.process_api_validation_errors(
                    patch_asset_response.json().get("message")
                )
                asset = db.session.get(GenericAsset, id)
        session["msg"] = msg
        return redirect(url_for("AssetCrudUI:properties", id=asset.id))

    @login_required
    def delete_with_data(self, id: str):
        """Delete via /assets/delete_with_data/<id>"""
        InternalApi().delete(url_for("AssetAPI:delete", id=id))
        return self.index(
            msg=f"Asset {id} and assorted meter readings / forecasts have been deleted."
        )

    @login_required
    @route("/<id>/auditlog")
    def auditlog(self, id: str):
        """/assets/<id>/auditlog"""
        get_asset_response = InternalApi().get(url_for("AssetAPI:fetch_one", id=id))
        asset_dict = get_asset_response.json()
        asset = process_internal_api_response(asset_dict, int(id), make_obj=True)

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

        get_asset_response = InternalApi().get(url_for("AssetAPI:fetch_one", id=id))
        asset_dict = get_asset_response.json()

        asset = process_internal_api_response(asset_dict, int(id), make_obj=True)

        asset_form = AssetForm()
        asset_form.with_options()

        asset_form.process(data=process_internal_api_response(asset_dict))

        return render_flexmeasures_template(
            "assets/asset_graph.html",
            asset=asset,
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
        get_asset_response = InternalApi().get(url_for("AssetAPI:fetch_one", id=id))
        asset_dict = get_asset_response.json()

        asset = process_internal_api_response(asset_dict, int(id), make_obj=True)

        asset_form = AssetForm()
        asset_form.with_options()

        asset_form.process(data=process_internal_api_response(asset_dict))

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

        return render_flexmeasures_template(
            "assets/asset_properties.html",
            asset=asset,
            asset_summary=asset_summary,
            asset_form=asset_form,
            msg=msg,
            mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
            user_can_create_assets=user_can_create_assets(),
            user_can_delete_asset=user_can_delete(asset),
            user_can_update_asset=user_can_update(asset),
            current_page="Properties",
        )
