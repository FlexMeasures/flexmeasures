from typing import Union, Optional, Tuple
import copy

from flask import url_for, current_app
from flask_classful import FlaskView
from flask_wtf import FlaskForm
from flask_security import login_required, current_user
from wtforms import StringField, DecimalField, SelectField
from wtforms.validators import DataRequired
from flexmeasures.auth.policy import ADMIN_ROLE

from flexmeasures.data import db
from flexmeasures.auth.error_handling import unauthorized_handler
from flexmeasures.data.models.generic_assets import (
    GenericAssetType,
    GenericAsset,
    get_center_location_of_assets,
)
from flexmeasures.data.models.user import Account
from flexmeasures.data.models.time_series import Sensor
from flexmeasures.ui.charts.latest_state import get_latest_power_as_plot
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template
from flexmeasures.ui.crud.api_wrapper import InternalApi
from flexmeasures.utils.unit_utils import is_power_unit


"""
Asset crud view.

Note: This uses the internal dev API version
      ― if those endpoints get moved or updated to a higher version,
      we probably should change the version used here, as well.
"""


class AssetForm(FlaskForm):
    """The default asset form only allows to edit the name and location."""

    name = StringField("Name")
    latitude = DecimalField(
        "Latitude",
        places=4,
        render_kw={"placeholder": "--Click the map or enter a latitude--"},
    )
    longitude = DecimalField(
        "Longitude",
        places=4,
        render_kw={"placeholder": "--Click the map or enter a longitude--"},
    )

    def validate_on_submit(self):
        if (
            hasattr(self, "generic_asset_type_id")
            and self.generic_asset_type_id.data == -1
        ):
            self.generic_asset_type_id.data = (
                ""  # cannot be coerced to int so will be flagged as invalid input
            )
        if hasattr(self, "account_id") and self.account_id.data == -1:
            del self.account_id  # asset will be public
        return super().validate_on_submit()

    def to_json(self) -> dict:
        """turn form data into a JSON we can POST to our internal API"""
        data = copy.copy(self.data)
        data["longitude"] = float(data["longitude"])
        data["latitude"] = float(data["latitude"])

        if "csrf_token" in data:
            del data["csrf_token"]

        return data

    def process_api_validation_errors(self, api_response: dict):
        """Process form errors from the API for the WTForm"""
        if not isinstance(api_response, dict):
            return
        for error_header in ("json", "validation_errors"):
            if error_header not in api_response:
                continue
            for field in list(self._fields.keys()):
                if field in list(api_response[error_header].keys()):
                    self._fields[field].errors.append(api_response[error_header][field])


class NewAssetForm(AssetForm):
    """Here, in addition, we allow to set asset type and account."""

    generic_asset_type_id = SelectField(
        "Asset type", coerce=int, validators=[DataRequired()]
    )
    account_id = SelectField("Account", coerce=int)


def with_options(
    form: Union[AssetForm, NewAssetForm]
) -> Union[AssetForm, NewAssetForm]:
    if "generic_asset_type_id" in form:
        form.generic_asset_type_id.choices = [(-1, "--Select type--")] + [
            (atype.id, atype.name) for atype in GenericAssetType.query.all()
        ]
    if "account_id" in form:
        form.account_id.choices = [(-1, "--Select account--")] + [
            (account.id, account.name) for account in Account.query.all()
        ]
    return form


def process_internal_api_response(
    asset_data: dict, asset_id: Optional[int] = None, make_obj=False
) -> Union[GenericAsset, dict]:
    """
    Turn data from the internal API into something we can use to further populate the UI.
    Either as an asset object or a dict for form filling.
    """

    def expunge_asset():
        # use if no insert is wanted from a previous query which flushes its results
        if asset in db.session:
            db.session.expunge(asset)

    asset_data.pop("status", None)  # might have come from requests.response
    if asset_id:
        asset_data["id"] = asset_id
    if make_obj:
        asset = GenericAsset(**asset_data)  # TODO: use schema?
        asset.generic_asset_type = GenericAssetType.query.get(
            asset.generic_asset_type_id
        )
        if "id" in asset_data:
            expunge_asset()
            asset.sensors = Sensor.query.filter(
                Sensor.generic_asset_id == asset_data["id"]
            ).all()
        expunge_asset()
        return asset
    return asset_data


class AssetCrudUI(FlaskView):
    """
    These views help us offer a Jinja2-based UI.
    The main focus on logic is the API, so these views simply call the API functions,
    and deal with the response.
    Some new functionality, like fetching accounts and asset types, is added here.
    """

    route_base = "/assets"

    @login_required
    def index(self, msg=""):
        """/assets"""
        get_assets_response = InternalApi().get(
            url_for("AssetAPI:index"), query={"account_id": current_user.account_id}
        )
        assets = [
            process_internal_api_response(ad, make_obj=True)
            for ad in get_assets_response.json()
        ]
        return render_flexmeasures_template(
            "crud/assets.html", account=current_user.account, assets=assets, message=msg
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
        return render_flexmeasures_template(
            "crud/assets.html",
            account=Account.query.get(account_id),
            assets=assets,
            msg=msg,
        )

    @login_required
    def get(self, id: str):
        """GET from /assets/<id> where id can be 'new' (and thus the form for asset creation is shown)"""

        if id == "new":
            if not current_user.has_role("admin"):
                return unauthorized_handler(None, [])

            asset_form = with_options(NewAssetForm())
            return render_flexmeasures_template(
                "crud/asset_new.html",
                asset_form=asset_form,
                msg="",
                map_center=get_center_location_of_assets(user=current_user),
                mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
            )

        get_asset_response = InternalApi().get(url_for("AssetAPI:fetch_one", id=id))
        asset_dict = get_asset_response.json()

        asset_form = with_options(AssetForm())

        asset = process_internal_api_response(asset_dict, int(id), make_obj=True)
        asset_form.process(data=process_internal_api_response(asset_dict))

        latest_measurement_time_str, asset_plot_html = _get_latest_power_plot(asset)
        return render_flexmeasures_template(
            "crud/asset.html",
            asset=asset,
            asset_form=asset_form,
            msg="",
            latest_measurement_time_str=latest_measurement_time_str,
            asset_plot_html=asset_plot_html,
            mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
        )

    @login_required
    def post(self, id: str):
        """POST to /assets/<id>, where id can be 'create' (and thus a new asset is made from POST data)
        Most of the code deals with creating a user for the asset if no existing is chosen.
        """

        asset: GenericAsset = None
        error_msg = ""

        if id == "create":
            asset_form = with_options(NewAssetForm())

            account, account_error = _set_account(asset_form)
            asset_type, asset_type_error = _set_asset_type(asset_form)

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
                    if (
                        "message" in post_asset_response.json()
                        and "json" in post_asset_response.json()["message"]
                    ):
                        error_msg = str(post_asset_response.json()["message"]["json"])
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
            asset_form = with_options(AssetForm())
            if not asset_form.validate_on_submit():
                asset = GenericAsset.query.get(id)
                latest_measurement_time_str, asset_plot_html = _get_latest_power_plot(
                    asset
                )
                # Display the form data, but set some extra data which the page wants to show.
                asset_info = asset_form.to_json()
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
                    latest_measurement_time_str=latest_measurement_time_str,
                    asset_plot_html=asset_plot_html,
                    mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
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
                asset_form.process_api_validation_errors(patch_asset_response.json())
                asset = GenericAsset.query.get(id)

        latest_measurement_time_str, asset_plot_html = _get_latest_power_plot(asset)
        return render_flexmeasures_template(
            "crud/asset.html",
            asset=asset,
            asset_form=asset_form,
            msg=msg,
            latest_measurement_time_str=latest_measurement_time_str,
            asset_plot_html=asset_plot_html,
            mapboxAccessToken=current_app.config.get("MAPBOX_ACCESS_TOKEN", ""),
        )

    @login_required
    def delete_with_data(self, id: str):
        """Delete via /assets/delete_with_data/<id>"""
        InternalApi().delete(url_for("AssetAPI:delete", id=id))
        return self.index(
            msg=f"Asset {id} and assorted meter readings / forecasts have been deleted."
        )


def _set_account(asset_form: NewAssetForm) -> Tuple[Optional[Account], Optional[str]]:
    """Set an account for the to-be-created asset.
    Return the account (if available) and an error message"""
    account = None
    account_error = None

    if asset_form.account_id.data == -1:
        if current_user.has_role(ADMIN_ROLE):
            return None, None  # Account can be None (public asset)
        else:
            account_error = "Please pick an existing account."

    account = Account.query.filter_by(id=int(asset_form.account_id.data)).one_or_none()

    if account:
        asset_form.account_id.data = account.id
    else:
        current_app.logger.error(account_error)
    return account, account_error


def _set_asset_type(
    asset_form: NewAssetForm,
) -> Tuple[Optional[GenericAssetType], Optional[str]]:
    """Set an asset type for the to-be-created asset.
    Return the asset type (if available) and an error message."""
    asset_type = None
    asset_type_error = None

    if int(asset_form.generic_asset_type_id.data) == -1:
        asset_type_error = "Pick an existing asset type."
    else:
        asset_type = GenericAssetType.query.filter_by(
            id=int(asset_form.generic_asset_type_id.data)
        ).one_or_none()

    if asset_type:
        asset_form.generic_asset_type_id.data = asset_type.id
    else:
        current_app.logger.error(asset_type_error)
    return asset_type, asset_type_error


def _get_latest_power_plot(asset: GenericAsset) -> Tuple[str, str]:
    power_sensor: Optional[Sensor] = None
    if asset._sa_instance_state.transient:
        sensors = Sensor.query.filter(Sensor.generic_asset_id == asset.id).all()
    else:
        sensors = asset.sensors
    for sensor in sensors:
        if is_power_unit(sensor.unit):
            power_sensor = sensor
            break
    if power_sensor is None:
        return "", ""
    else:
        return get_latest_power_as_plot(power_sensor)
