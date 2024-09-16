from __future__ import annotations
from flask import url_for, current_app, request
from flask_classful import FlaskView, route
from flask_security import login_required, current_user
from webargs.flaskparser import use_kwargs

from flexmeasures.data import db
from flexmeasures.auth.error_handling import unauthorized_handler
from flexmeasures.data.schemas import StartEndTimeSchema
from flexmeasures.data.services.job_cache import NoRedisConfigured
from flexmeasures.data.models.generic_assets import (
    GenericAsset,
    get_center_location_of_assets,
)
from flexmeasures.ui.utils.view_utils import ICON_MAPPING
from flexmeasures.data.models.user import Account
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template
from flexmeasures.ui.crud.api_wrapper import InternalApi
from flexmeasures.ui.crud.assets.forms import NewAssetForm, AssetForm
from flexmeasures.ui.crud.assets.utils import (
    process_internal_api_response,
    user_can_create_assets,
    user_can_delete,
)
from flexmeasures.data.services.sensors import (
    build_sensor_status_data,
    build_asset_jobs_data,
)


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
            "crud/assets.html",
            asset_icon_map=ICON_MAPPING,
            message=msg,
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
            "crud/assets.html",
            account=db.session.get(Account, account_id),
            assets=assets,
            msg=msg,
            user_can_create_assets=user_can_create_assets(),
        )

    @use_kwargs(StartEndTimeSchema, location="query")
    @login_required
    def get(self, id: str, **kwargs):
        """GET from /assets/<id> where id can be 'new' (and thus the form for asset creation is shown)
        The following query parameters are supported (should be used only together):
         - start_time: minimum time of the events to be shown
         - end_time: maximum time of the events to be shown
        """
        if id == "new":
            if not user_can_create_assets():
                return unauthorized_handler(None, [])

            asset_form = NewAssetForm()
            asset_form.with_options()
            asset_form.with_sensors(None, None)
            return render_flexmeasures_template(
                "crud/asset_new.html",
                asset_form=asset_form,
                msg="",
                map_center=get_center_location_of_assets(user=current_user),
                mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
            )

        get_asset_response = InternalApi().get(url_for("AssetAPI:fetch_one", id=id))
        asset_dict = get_asset_response.json()
        asset = process_internal_api_response(asset_dict, int(id), make_obj=True)

        asset_form = AssetForm()
        asset_form.with_options()
        asset_form.with_sensors(asset, asset.account_id)

        asset_form.process(data=process_internal_api_response(asset_dict))

        return render_flexmeasures_template(
            "crud/asset.html",
            asset=asset,
            asset_form=asset_form,
            msg="",
            mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
            user_can_create_assets=user_can_create_assets(),
            user_can_delete_asset=user_can_delete(asset),
            event_starts_after=request.args.get("start_time"),
            event_ends_before=request.args.get("end_time"),
        )

    @login_required
    @route("/<id>/status")
    def status(self, id: str):
        """GET from /assets/<id>/status to show the staleness of the asset's sensors."""

        get_asset_response = InternalApi().get(url_for("AssetAPI:fetch_one", id=id))
        asset_dict = get_asset_response.json()

        asset = process_internal_api_response(asset_dict, int(id), make_obj=True)
        status_data = build_sensor_status_data(asset)

        # add data about forecasting and scheduling jobs
        redis_connection_err = None
        all_jobs_data = list()
        try:
            jobs_data = build_asset_jobs_data(asset)
        except NoRedisConfigured as e:
            redis_connection_err = e.args[0]
        else:
            all_jobs_data = jobs_data

        return render_flexmeasures_template(
            "views/status.html",
            asset=asset,
            sensors=status_data,
            jobs_data=all_jobs_data,
            redis_connection_err=redis_connection_err,
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

            account_id = account.id if account else None
            asset_form.with_sensors(None, account_id)

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
                    "crud/asset_new.html",
                    asset_form=asset_form,
                    msg=msg,
                    map_center=get_center_location_of_assets(user=current_user),
                    mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
                )

        else:
            asset = db.session.get(GenericAsset, id)
            asset_form = AssetForm()
            asset_form.with_options()
            asset_form.with_sensors(asset, asset.account_id)
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

                return render_flexmeasures_template(
                    "crud/asset.html",
                    asset_form=asset_form,
                    asset=asset,
                    msg="Cannot edit asset.",
                    mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
                    user_can_create_assets=user_can_create_assets(),
                    user_can_delete_asset=user_can_delete(asset),
                )
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

        return render_flexmeasures_template(
            "crud/asset.html",
            asset=asset,
            asset_form=asset_form,
            msg=msg,
            mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
            user_can_create_assets=user_can_create_assets(),
            user_can_delete_asset=user_can_delete(asset),
        )

    @login_required
    def delete_with_data(self, id: str):
        """Delete via /assets/delete_with_data/<id>"""
        InternalApi().delete(url_for("AssetAPI:delete", id=id))
        return self.index(
            msg=f"Asset {id} and assorted meter readings / forecasts have been deleted."
        )

    @login_required
    def auditlog(self, id: str):
        """/assets/auditlog/<id>"""
        get_asset_response = InternalApi().get(url_for("AssetAPI:fetch_one", id=id))
        asset_dict = get_asset_response.json()
        asset = process_internal_api_response(asset_dict, int(id), make_obj=True)

        audit_log_response = InternalApi().get(url_for("AssetAPI:auditlog", id=id))
        audit_logs_response = audit_log_response.json()
        return render_flexmeasures_template(
            "crud/asset_audit_log.html",
            audit_logs=audit_logs_response,
            asset=asset,
        )
