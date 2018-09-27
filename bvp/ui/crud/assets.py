from typing import Optional, Tuple

from flask import request
from flask_classful import FlaskView
from flask_wtf import FlaskForm
from wtforms import StringField, DecimalField, SelectField
from wtforms.validators import DataRequired, NumberRange, Length
from flask_security import login_required, roles_required, current_user
from werkzeug.exceptions import NotFound
from sqlalchemy.exc import IntegrityError

from bvp.data.services.resources import get_assets, create_asset
from bvp.ui.utils.view_utils import render_bvp_template
from bvp.data.models.assets import Asset, AssetType
from bvp.data.models.user import User
from bvp.data.services.users import get_users, create_user, InvalidBVPUser
from bvp.data.services.resources import delete_asset
from bvp.data.auth_setup import unauth_handler
from bvp.data.config import db


class AssetForm(FlaskForm):
    """The default asset form only allows to edit the name and numbers"""

    display_name = StringField(
        "Display name", validators=[DataRequired(), Length(min=4)]
    )
    capacity_in_mw = DecimalField(
        "Capacity in MW", places=2, validators=[NumberRange(min=0)]
    )
    min_soc_in_mwh = DecimalField(
        "Minumum state of charge (SOC) in MWh",
        places=2,
        default=0,
        validators=[NumberRange(min=0)],
    )
    max_soc_in_mwh = DecimalField(
        "Maximum state of charge (SOC) in MWh",
        places=2,
        default=0,
        validators=[NumberRange(min=0)],
    )
    latitude = DecimalField(
        "Latitude",
        places=4,
        render_kw={"placeholder": "--Click the map or enter a latitude --"},
        validators=[NumberRange(min=-90, max=90)],
    )
    longitude = DecimalField(
        "Longitude",
        places=4,
        render_kw={"placeholder": "--Click the map or enter a longitude--"},
        validators=[NumberRange(min=-180, max=180)],
    )

    def validate_on_submit(self):
        form_valid = super().validate_on_submit()
        if self.max_soc_in_mwh.data < self.min_soc_in_mwh.data:
            self.errors["max_soc_in_mwh"] = [
                "This value must be equal or higher than the minimum soc."
            ]
            return False
        return form_valid


class NewAssetForm(AssetForm):
    """Here we allow to set asset type and owner"""

    asset_type_name = SelectField("asset type", validators=[DataRequired()])
    owner = SelectField("owner")


def with_options(form: NewAssetForm) -> NewAssetForm:
    form.asset_type_name.choices = [("none chosen", "--Select type--")] + [
        (atype.name, atype.name) for atype in AssetType.query.all()
    ]
    form.owner.choices = [("none chosen", "--Select existing or add new below--")] + [
        (o.id, o.username) for o in get_users(role_name="Prosumer")
    ]
    return form


class AssetCrud(FlaskView):
    route_base = "/assets"
    trailing_slash = False

    @login_required
    def index(self):
        """/assets"""
        assets = get_assets()
        return render_bvp_template("crud/assets.html", assets=assets)

    @login_required
    def owned_by(self, owner_id: Optional[str]):
        """/assets/owned_by/<user_id>"""
        if not (current_user.has_role("admin") or int(owner_id) == current_user.id):
            return unauth_handler()
        assets = get_assets(owner_id)
        return render_bvp_template("crud/assets.html", assets=assets)

    @login_required
    def get(self, id: str):
        """GET from /assets/<id> where id can be 'new' (and thus the form for asset creation is shown)"""

        if id == "new":
            asset_form = with_options(NewAssetForm())
            if not current_user.has_role("admin"):
                return unauth_handler()

            return render_bvp_template(
                "crud/asset_new.html", asset_form=asset_form, msg=""
            )

        asset_form = AssetForm()
        asset: Asset = Asset.query.filter_by(id=int(id)).one_or_none()
        if asset is not None:
            if asset.owner != current_user and not current_user.has_role("admin"):
                return unauth_handler()
            asset_form.process(obj=asset)
            return render_bvp_template(
                "crud/asset.html", asset=asset, asset_form=asset_form, msg=""
            )
        else:
            raise NotFound

    @login_required
    def post(self, id: str):
        """POST to /assets/<id>, where id can be 'create' (and thus a new asset is made from POST data)
           Most of the code deals with creating a user for the asset if no existing is chosen.
        """

        if id == "create":
            if not current_user.has_role("admin"):
                return unauth_handler()

            asset_form = with_options(NewAssetForm())

            owner, owner_error = get_or_create_owner(asset_form)

            if asset_form.asset_type_name.data == "none chosen":
                asset_form.asset_type_name.data = ""

            form_valid = asset_form.validate_on_submit()

            if owner_error is not None:
                asset_form.errors["owner"] = [owner_error]
            else:
                asset_form.errors["owner"] = []

            if form_valid and owner is not None:
                asset = create_asset(
                    display_name=asset_form.display_name.data,
                    asset_type_name=asset_form.asset_type_name.data,
                    capacity_in_mw=asset_form.capacity_in_mw.data,
                    latitude=asset_form.latitude.data,
                    longitude=asset_form.longitude.data,
                    min_soc_in_mwh=asset_form.min_soc_in_mwh.data,
                    max_soc_in_mwh=asset_form.max_soc_in_mwh.data,
                    soc_in_mwh=0,
                    owner=owner,
                )
                asset_form.process(obj=asset)
                asset_form.owner.data = owner.id
                db.session.flush()  # the object should get the ID here, for the form to be rendered correctly
                msg = "Creation was successful."
            else:
                msg = "Cannot create asset."
                return render_bvp_template(
                    "crud/asset_new.html", asset_form=asset_form, msg=msg
                )
        else:
            asset_form = AssetForm()
            asset: Asset = Asset.query.filter_by(id=int(id)).one_or_none()
            if asset is not None:
                if asset.owner != current_user and not current_user.has_role("admin"):
                    return unauth_handler()
                if asset_form.validate_on_submit():
                    asset_form.populate_obj(asset)
                    msg = "Editing was successful."
                else:
                    msg = "Asset was not saved, please review error(s) below."
            else:
                raise NotFound
        return render_bvp_template(
            "crud/asset.html", asset=asset, asset_form=asset_form, msg=msg
        )

    @roles_required("admin")
    def delete_with_data(self, id: str):
        """Delete via /assets/delete_with_data/<id>"""
        asset: Asset = Asset.query.filter_by(id=int(id)).one_or_none()
        asset_name = asset.name
        delete_asset(asset)
        return render_bvp_template(
            "crud/assets.html",
            msg="Asset %s and assorted meter readings / forecasts have been deleted."
            % asset_name,
            assets=get_assets(),
        )


def get_or_create_owner(asset_form: NewAssetForm) -> Tuple[Optional[User], str]:
    """Get an existing or create a new User as owner for the to-be-created asset.
    Return the user (if available and an error message)"""
    owner = None
    owner_error = None

    if asset_form.owner.data == "none chosen":
        new_owner_email = request.form.get("new_owner_email")
        if new_owner_email.startswith("--Type"):
            owner_error = "Either pick an existing user as owner or enter an email address for the new owner."
        else:
            try:
                owner = create_user(email=new_owner_email, user_roles=["Prosumer"])
            except InvalidBVPUser as e:
                owner_error = str(e)
            except IntegrityError as e:
                owner_error = "New owner cannot be created."
            asset_form.owner.choices.append((owner.id, owner.username))
    else:
        owner = User.query.filter_by(id=int(asset_form.owner.data)).one_or_none()

    if owner:
        asset_form.owner.data = owner.id
    return owner, owner_error
