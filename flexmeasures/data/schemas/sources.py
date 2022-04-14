from flask.cli import with_appcontext
from marshmallow import fields

from flexmeasures.data.models.data_sources import DataSource
from flexmeasures.data.schemas.utils import FMValidationError, MarshmallowClickMixin


class DataSourceIdField(fields.Int, MarshmallowClickMixin):
    """Field that deserializes to a Sensor and serializes back to an integer."""

    @with_appcontext
    def _deserialize(self, value, attr, obj, **kwargs) -> DataSource:
        """Turn a source id into a DataSource."""
        source = DataSource.query.get(value)
        if source is None:
            raise FMValidationError(f"No data source found with id {value}.")
        return source

    def _serialize(self, source, attr, data, **kwargs):
        """Turn a DataSource into a source id."""
        return source.id
