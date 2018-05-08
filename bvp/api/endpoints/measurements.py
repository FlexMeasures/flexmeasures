from datetime import datetime

from bvp.models.measurements import Measurement
from bvp.models.assets import Asset
# from bvp.models.user import User
from bvp.api import ma, bvp_api


class MeasurementSchema(ma.ModelSchema):
    """For some neat tricks, read
    https://marshmallow-sqlalchemy.readthedocs.io/en/latest/recipes.html#overriding-generated-fields
    e.g. for getting other asset info in there than the ID
    """
    class Meta:
        model = Measurement
        fields = ('datetime', 'value')


@bvp_api.route('/api/measurements')
def measurements_get():
    """
    Use marshmallow to connect SQLAlchemy-modelled data to the outside world.
    Just a demonstration for now. Needs more work.
    TODO: let's support a version from day one.
    """
    start = datetime(2015, 2, 10, 2)
    end = datetime(2015, 2, 10, 4)
    asset = Asset.query.all()[6]
    print("Chose Asset %s, id: %s" % (asset, asset.id))
    # TODO: only assets owned by user (or user is admin)
    measurements = Measurement.query.filter((Measurement.datetime >= start)
                                            & (Measurement.datetime <= end)
                                            & (Measurement.asset_id == asset.id)).all()
    response = MeasurementSchema().jsonify(measurements, many=True)
    return response
