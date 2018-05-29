from datetime import datetime

from flask_security import auth_token_required, current_user

from bvp.data.models.assets import Power
# from bvp.data.models.user import User
from bvp.api import ma, bvp_api
from bvp.data.services import get_assets


class PowerSchema(ma.ModelSchema):
    """For some neat tricks, read
    https://marshmallow-sqlalchemy.readthedocs.io/en/latest/recipes.html#overriding-generated-fields
    e.g. for getting other asset info in there
    """
    class Meta:
        model = Power
        fields = ('datetime', 'value')


@bvp_api.route('/api/power')
@auth_token_required
def power_get():
    """
    Use marshmallow to connect SQLAlchemy-modelled data to the outside world.
    Just a demonstration for now. Needs more work.
    TODO: let's support a version from day one.
    """
    start = datetime(2015, 2, 10, 2)
    end = datetime(2015, 2, 10, 4)
    asset = get_assets()[0]
    print("For user %s, I chose Asset %s, id: %s" % (current_user, asset, asset.id))
    # TODO: use bvp.data.services.get_power? Maybe make it possible to return the actual DB objects we want here.
    measurements = Power.query.filter((Power.datetime >= start)
                                       & (Power.datetime <= end)
                                       & (Power.asset_id == asset.id)).all()
    response = PowerSchema().jsonify(measurements, many=True)
    return response
