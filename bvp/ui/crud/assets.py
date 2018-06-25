from flask_classful import FlaskView
from flask_wtf import FlaskForm
from wtforms import StringField, FloatField
from wtforms.validators import DataRequired
from flask_security import login_required, current_user
from werkzeug.exceptions import NotFound

from bvp.data.services import get_assets
from bvp.ui.utils.view_utils import (
    render_bvp_template,
    get_addressing_scheme,
    get_naming_authority,
)
from bvp.data.models.assets import Asset
from bvp.data.config import db
from bvp.data.auth_setup import unauth_handler


class AssetForm(FlaskForm):
    display_name = StringField("Display name", validators=[DataRequired()])
    capacity_in_mw = FloatField("Capacity in MW", validators=[DataRequired()])
    latitude = FloatField("Latitude", validators=[DataRequired()])
    longitude = FloatField("Longitude", validators=[DataRequired()])


class AssetCrud(FlaskView):
    route_base = "/assets"

    @login_required
    def index(self):
        """/assets"""
        assets = get_assets()
        return render_bvp_template(
            "crud/assets.html",
            assets=assets,
            get_addressing_scheme=get_addressing_scheme,
            get_naming_authority=get_naming_authority,
        )

    @login_required
    def get(self, id: str):
        """GET from /assets/<id>"""
        asset: Asset = Asset.query.filter_by(id=int(id)).one_or_none()
        if asset is not None:
            if asset.owner != current_user and not current_user.has_role("admin"):
                return unauth_handler()
            asset_form = AssetForm()
            asset_form.process(obj=asset)
            return render_bvp_template(
                "crud/asset.html",
                asset=asset,
                asset_form=asset_form,
                msg="",
                get_addressing_scheme=get_addressing_scheme,
                get_naming_authority=get_naming_authority,
            )
        else:
            raise NotFound

    @login_required
    def post(self, id: str):
        """POST to /assets/<id>"""
        asset: Asset = Asset.query.filter_by(id=int(id)).one_or_none()
        if asset is not None:
            if asset.owner != current_user and not current_user.has_role("admin"):
                return unauth_handler()
            asset_form = AssetForm()
            asset_form.populate_obj(asset)
            db.session.add(asset)
            db.session.commit()
            return render_bvp_template(
                "crud/asset.html",
                asset=asset,
                asset_form=asset_form,
                msg="Editing was successful.",
                get_addressing_scheme=get_addressing_scheme,
                get_naming_authority=get_naming_authority,
            )
        else:
            raise NotFound
