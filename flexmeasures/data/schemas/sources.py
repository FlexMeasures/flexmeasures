from marshmallow import fields, validate

from flexmeasures.data import ma, db
from flexmeasures.data.models.data_sources import DataSource, DEFAULT_DATASOURCE_TYPES
from flexmeasures.data.schemas.utils import (
    with_appcontext_if_needed,
    FMValidationError,
    MarshmallowClickMixin,
)


class DataSourceSchema(ma.SQLAlchemySchema):
    """
    DataSource schema.
    """

    id = ma.auto_field()
    name = fields.Str()
    type = fields.Str(validate=validate.OneOf(choices=DEFAULT_DATASOURCE_TYPES))

    class Meta:
        model = DataSource


class DataSourcesSchema(DataSourceSchema):
    class Meta:
        many = True


class DataSourceIdField(fields.Int, MarshmallowClickMixin):
    """Field that deserializes to a DataSource and serializes back to an integer."""

    @with_appcontext_if_needed()
    def _deserialize(self, value, attr, obj, **kwargs) -> DataSource:
        """Turn a source id into a DataSource."""
        value = super()._deserialize(value, attr, obj, **kwargs)
        source = db.session.get(DataSource, value)
        if source is None:
            raise FMValidationError(f"No data source found with id {value}.")
        return source

    def _serialize(self, source, attr, data, **kwargs):
        """Turn a DataSource into a source id."""
        return source.id
