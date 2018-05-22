from datetime import datetime

from flask_security import auth_token_required, current_user

from bvp.models.measurements import Measurement
# from bvp.models.user import User
from bvp.api import ma, bvp_api
from bvp.utils.data_access import get_assets


class MeasurementSchema(ma.ModelSchema):
    """For some neat tricks, read
    https://marshmallow-sqlalchemy.readthedocs.io/en/latest/recipes.html#overriding-generated-fields
    e.g. for getting other asset info in there than the ID
    """
    class Meta:
        model = Measurement
        fields = ('datetime', 'value')


@bvp_api.route('/api/measurements')
@auth_token_required
def measurements_get():
    """
    Use marshmallow to connect SQLAlchemy-modelled data to the outside world.
    Just a demonstration for now. Needs more work.
    TODO: let's support a version from day one.
    """
    start = datetime(2015, 2, 10, 2)
    end = datetime(2015, 2, 10, 4)
    asset = get_assets()[0]
    print("For user %s, I chose Asset %s, id: %s" % (current_user, asset, asset.id))
    measurements = Measurement.query.filter((Measurement.datetime >= start)
                                            & (Measurement.datetime <= end)
                                            & (Measurement.asset_id == asset.id)).all()
    response = MeasurementSchema().jsonify(measurements, many=True)
    return response
