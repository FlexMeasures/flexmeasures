from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy import Column, DateTime, Float, String


# Time resolutions
resolutions = ["15T", "1h", "1d", "1w"]

# The confidence interval for forecasting
confidence_interval_width = .9


class ModelException(Exception):
    pass


class TimedValue(object):
    """
    A mixin of all tables that store time series data, either forecasts or measurements.
    """

    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()

    """The time at which the value is supposed to (have) happen(ed)."""

    @declared_attr
    def datetime(cls):
        return Column(DateTime(timezone=True), primary_key=True)

    """The time delta of measuring or forecasting.
    This should be a duration in ISO8601, e.g. "-PT10M".
    Positive durations indicate a forecast, negative ones a measurement after the fact.
    We're trying to use little space here, expand later if necessary."""

    @declared_attr
    def horizon(cls):
        return Column(String(6), nullable=False)

    """The value."""

    @declared_attr
    def value(cls):
        return Column(Float, nullable=False)
