from typing import Union, Optional, Tuple
from datetime import timedelta
import copy

from flask import request, url_for, current_app
from flask_classful import FlaskView
from flask_wtf import FlaskForm
from flask_security import login_required, current_user
from wtforms import StringField, DecimalField, IntegerField, SelectField
from wtforms.validators import DataRequired
from sqlalchemy.exc import IntegrityError

from flexmeasures.data.auth_setup import unauthorized_handler
from flexmeasures.data.services.users import (
    get_users,
    create_user,
    InvalidFlexMeasuresUser,
)
from flexmeasures.data.services.resources import get_markets
from flexmeasures.data.models.assets import AssetType, Asset
from flexmeasures.data.models.user import User
from flexmeasures.data.models.markets import Market
from flexmeasures.ui.utils.plotting_utils import get_latest_power_as_plot
from flexmeasures.ui.utils.view_utils import render_flexmeasures_template
from flexmeasures.ui.crud.api_wrapper import InternalApi


class AssetForm(FlaskForm):
    """The default asset form only allows to edit the name, numbers and market."""

    display_name = StringField("Display name")
    capacity_in_mw = DecimalField("Capacity in MW", places=2)
    unit = SelectField("Unit", default="MW", choices=[("MW", "MW")])
    event_resolution = IntegerField(
        "Resolution in minutes (e.g. 15)",
        default=15,
    )
    min_soc_in_mwh = DecimalField(
        "Minimum state of charge (SOC) in MWh",
        places=2,
        default=0,
    )
    max_soc_in_mwh = DecimalField(
        "Maximum state of charge (SOC) in MWh",
        places=2,
        default=0,
    )
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
    market_id = SelectField("Market", coerce=int)

    def validate_on_submit(self):
        if self.market_id.data == -1:
            self.market_id.data = (
                ""  # cannot be coerced to int so will be flagged as invalid input
            )
        return super().validate_on_submit()

    def to_json(self) -> dict:
        """ turn form data into a JSON we can POST to our internal API """
        data = copy.copy(self.data)
        data["name"] = data["display_name"]  # both are part of the asset model
        data[
            "unit"
        ] = "MW"  # TODO: make unit a choice? this is hard-coded in the UI as well
        data["capacity_in_mw"] = float(data["capacity_in_mw"])
        data["min_soc_in_mwh"] = float(data["min_soc_in_mwh"])
        data["max_soc_in_mwh"] = float(data["max_soc_in_mwh"])
        data["longitude"] = float(data["longitude"])
        data["latitude"] = float(data["latitude"])
        if "owner" in data:
            data["owner_id"] = data.pop("owner")

        if "csrf_token" in data:
            del data["csrf_token"]

        return data

    def process_api_validation_errors(self, api_response: dict):
        """Process form errors from the API for the WTForm"""
        if (
            not isinstance(api_response, dict)
            or "validation_errors" not in api_response
        ):
            return
        for field in list(self._fields.keys()):
            if field in list(api_response["validation_errors"].keys()):
                self._fields[field].errors.append(
                    api_response["validation_errors"][field]
                )


class NewAssetForm(AssetForm):
    """Here, in addition, we allow to set asset type and owner."""

    asset_type_name = SelectField("Asset type", validators=[DataRequired()])
    owner = SelectField("Owner", coerce=int)


def with_options(
    form: Union[AssetForm, NewAssetForm]
) -> Union[AssetForm, NewAssetForm]:
    if "asset_type_name" in form:
        form.asset_type_name.choices = [("none chosen", "--Select type--")] + [
            (atype.name, atype.display_name) for atype in AssetType.query.all()
        ]
    if "owner" in form:
        form.owner.choices = [(-1, "--Select existing or add new below--")] + [
            (o.id, o.username) for o in get_users(role_name="Prosumer")
        ]
    if "market_id" in form:
        form.market_id.choices = [(-1, "--Select existing--")] + [
            (m.id, m.display_name) for m in get_markets()
        ]
    return form


def process_internal_api_response(
    asset_data: dict, asset_id: Optional[int] = None, make_obj=False
) -> Union[Asset, dict]:
    """
    Turn data from the internal API into something we can use to further populate the UI.
    Either as an asset object or a dict for form filling.
    """
    asset_data.pop("status", None)  # might have come from requests.response
    if asset_id:
        asset_data["id"] = asset_id
    if make_obj:
        asset_data["event_resolution"] = timedelta(
            minutes=int(asset_data["event_resolution"])
        )
        return Asset(**asset_data)
    asset_data["event_resolution"] = asset_data["event_resolution"].seconds / 60
    return asset_data


class AssetCrudUI(FlaskView):
    """
    These views help us offering a Jinja2-based UI.
    The main focus on logic is the API, so these views simply call the API functions,
    and deal with the response.
    Some new functionality, like fetching users and markets, is added here.
    """

    route_base = "/assets"

    @login_required
    def index(self, msg=""):
        """/assets"""
        get_assets_response = InternalApi().get(
            url_for("flexmeasures_api_v2_0.get_assets")
        )
        assets = [
            process_internal_api_response(ad, make_obj=True)
            for ad in get_assets_response.json()
        ]
        return render_flexmeasures_template(
            "crud/assets.html", assets=assets, message=msg
        )

    @login_required
    def owned_by(self, owner_id: str):
        """/assets/owned_by/<user_id>"""
        get_assets_response = InternalApi().get(
            url_for("flexmeasures_api_v2_0.get_assets"), query={"owner_id": owner_id}
        )
        assets = [
            process_internal_api_response(ad, make_obj=True)
            for ad in get_assets_response.json()
        ]
        return render_flexmeasures_template("crud/assets.html", assets=assets)

    @login_required
    def get(self, id: str):
        """GET from /assets/<id> where id can be 'new' (and thus the form for asset creation is shown)"""

        if id == "new":
            if not current_user.has_role("admin"):
                return unauthorized_handler(None, [])

            asset_form = with_options(NewAssetForm())
            return render_flexmeasures_template(
                "crud/asset_new.html", asset_form=asset_form, msg=""
            )

        get_asset_response = InternalApi().get(
            url_for("flexmeasures_api_v2_0.get_asset", id=id)
        )
        asset_dict = get_asset_response.json()

        asset_form = with_options(AssetForm())

        asset = process_internal_api_response(asset_dict, int(id), make_obj=True)
        asset_form.process(data=process_internal_api_response(asset_dict))

        latest_measurement_time_str, asset_plot_html = get_latest_power_as_plot(asset)
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

        asset: Asset = None
        error_msg = ""

        if id == "create":
            asset_form = with_options(NewAssetForm())

            # We make our own auth check here because set_owner might alter the DB;
            # otherwise we trust the API is handling auth.
            if not current_user.has_role("admin"):
                return unauthorized_handler(None, [])
            owner, owner_error = set_owner(asset_form, create_if_not_exists=True)
            market, market_error = set_market(asset_form)

            if asset_form.asset_type_name.data == "none chosen":
                asset_form.asset_type_name.data = ""

            form_valid = asset_form.validate_on_submit()

            # Fill up the form with useful errors for the user
            if owner_error is not None:
                form_valid = False
                asset_form.owner.errors.append(owner_error)
            if market_error is not None:
                form_valid = False
                asset_form.market_id.errors.append(market_error)

            # Create new asset or return the form for new assets with a message
            if form_valid and owner is not None and market is not None:
                post_asset_response = InternalApi().post(
                    url_for("flexmeasures_api_v2_0.post_assets"),
                    args=asset_form.to_json(),
                    do_not_raise_for=[400],
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
                        error_msg = post_asset_response.json()["message"]
            if asset is None:
                msg = "Cannot create asset. " + error_msg
                return render_flexmeasures_template(
                    "crud/asset_new.html", asset_form=asset_form, msg=msg
                )

        else:
            asset_form = with_options(AssetForm())
            if not asset_form.validate_on_submit():
                return render_flexmeasures_template(
                    "crud/asset_new.html",
                    asset_form=asset_form,
                    msg="Cannot edit asset.",
                )
            patch_asset_response = InternalApi().patch(
                url_for("flexmeasures_api_v2_0.patch_asset", id=id),
                args=asset_form.to_json(),
                do_not_raise_for=[400],
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
                asset_form.process_api_validation_errors(patch_asset_response.json())
                asset = Asset.query.get(id)

        latest_measurement_time_str, asset_plot_html = get_latest_power_as_plot(asset)
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
        InternalApi().delete(
            url_for("flexmeasures_api_v2_0.delete_asset", id=id),
        )
        return self.index(
            msg=f"Asset {id} and assorted meter readings / forecasts have been deleted."
        )


def set_owner(
    asset_form: NewAssetForm, create_if_not_exists: bool = False
) -> Tuple[Optional[User], Optional[str]]:
    """Set a user as owner for the to-be-created asset.
    Return the user (if available and an error message)"""
    owner = None
    owner_error = None

    if asset_form.owner.data == -1 and create_if_not_exists:
        new_owner_email = request.form.get("new_owner_email", "")
        if new_owner_email.startswith("--Type"):
            owner_error = "Either pick an existing user as owner or enter an email address for the new owner."
        else:
            try:
                owner = create_user(email=new_owner_email, user_roles=["Prosumer"])
            except InvalidFlexMeasuresUser as ibe:
                owner_error = str(ibe)
            except IntegrityError as ie:
                owner_error = "New owner cannot be created: %s" % str(ie)
            if owner:
                asset_form.owner.choices.append((owner.id, owner.username))
    else:
        owner = User.query.filter_by(id=int(asset_form.owner.data)).one_or_none()

    if owner:
        asset_form.owner.data = owner.id
    else:
        current_app.logger.error(owner_error)
    return owner, owner_error


def set_market(asset_form: NewAssetForm) -> Tuple[Optional[Market], Optional[str]]:
    """Set a market for the to-be-created asset.
    Return the market (if available) and an error message."""
    market = None
    market_error = None

    if int(asset_form.market_id.data) == -1:
        market_error = "Pick an existing market."
    else:
        market = Market.query.filter_by(id=int(asset_form.market_id.data)).one_or_none()

    if market:
        asset_form.market_id.data = market.id
    return market, market_error
