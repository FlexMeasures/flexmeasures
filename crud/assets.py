from flask_classful import FlaskView
from flask_wtf import FlaskForm
from wtforms import StringField, FloatField
from wtforms.validators import DataRequired
from flask_security import login_required

from utils.data_access import get_assets
from utils.view_utils import render_bvp_template
from models.assets import Asset
from database import db


class AssetForm(FlaskForm):
    display_name = StringField('Display name', validators=[DataRequired()])
    capacity_in_mw = FloatField('Capacity in MW', validators=[DataRequired()])
    latitude = FloatField('Latitude', validators=[DataRequired()])
    longitude = FloatField('Longitude', validators=[DataRequired()])


class AssetCrud(FlaskView):

    route_base = '/assets'

    @login_required
    def index(self):
        """/assets"""
        assets = get_assets()
        return render_bvp_template('crud/assets.html', assets=assets)

    @login_required
    def get(self, id: str):
        """GET from /assets/<id>"""
        asset: Asset = Asset.query.filter_by(id=int(id)).one_or_none()
        if asset is not None:
            asset_form = AssetForm()
            asset_form.process(obj=asset)
            return render_bvp_template("crud/asset.html", asset=asset, asset_form=asset_form, msg="")
        else:
            return "Not Found", 404

    @login_required
    def post(self, id: str):
        """POST to /assets/<id>"""
        asset: Asset = Asset.query.filter_by(id=int(id)).one_or_none()
        asset_form = AssetForm()
        asset_form.populate_obj(asset)
        db.session.add(asset)
        db.session.commit()
        return render_bvp_template("crud/asset.html", asset=asset, asset_form=asset_form, msg="Saving was successful.")
