from bvp.data.models.assets import Asset, Power
# from bvp.data.models.user import User
from bvp.api import ma, bvp_api


class PowerSchema(ma.ModelSchema):
    """For some neat tricks, read
    https://marshmallow-sqlalchemy.readthedocs.io/en/latest/recipes.html#overriding-generated-fields
    e.g. for getting other asset info in there
    """

    class Meta:
        model = Power
        fields = ("datetime", "value")
