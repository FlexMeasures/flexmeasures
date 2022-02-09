from datetime import timedelta

from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataSource


class Annotation(db.Model):
    """An annotation is a nominal value that applies to a specific time or time span.

    Examples of annotation types:
        - user annotation: annotation.type == "label" and annotation.source.type == "user"
        - unresolved alert: annotation.type == "alert"
        - resolved alert: annotation.type == "label" and annotation.source.type == "alerting script"
        - organisation holiday: annotation.type == "holiday" and annotation.source.type == "user"
        - public holiday: annotation.type == "holiday" and annotation.source.name == "workalendar"
    """

    id = db.Column(db.Integer, nullable=False, autoincrement=True, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    start = db.Column(db.DateTime(timezone=True), nullable=False)
    end = db.Column(db.DateTime(timezone=True), nullable=False)
    source_id = db.Column(db.Integer, db.ForeignKey(DataSource.__tablename__ + ".id"))
    source = db.relationship(
        "DataSource",
        foreign_keys=[source_id],
        backref=db.backref("annotations", lazy=True),
    )
    type = db.Column(db.Enum("alert", "holiday", "label", name="annotation_type"))
    __table_args__ = (
        db.UniqueConstraint(
            "name",
            "start",
            "source_id",
            "type",
            name="annotation_name_key",
        ),
    )

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def __repr__(self) -> str:
        return f"<Annotation {self.id}: {self.name} ({self.type}), start: {self.start} end: {self.end}, source: {self.source}>"


class GenericAssetAnnotationRelationship(db.Model):
    """Links annotations to generic assets."""

    __tablename__ = "annotations_assets"

    id = db.Column(db.Integer(), primary_key=True)
    generic_asset_id = db.Column(db.Integer, db.ForeignKey("generic_asset.id"))
    annotation_id = db.Column(db.Integer, db.ForeignKey("annotation.id"))


class SensorAnnotationRelationship(db.Model):
    """Links annotations to sensors."""

    __tablename__ = "annotations_sensors"

    id = db.Column(db.Integer(), primary_key=True)
    sensor_id = db.Column(db.Integer, db.ForeignKey("sensor.id"))
    annotation_id = db.Column(db.Integer, db.ForeignKey("annotation.id"))
