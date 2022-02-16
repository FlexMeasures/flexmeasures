from datetime import timedelta

from flexmeasures.data import db


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
    content = db.Column(db.String(255), nullable=False)
    start = db.Column(db.DateTime(timezone=True), nullable=False)
    end = db.Column(db.DateTime(timezone=True), nullable=False)
    source_id = db.Column(db.Integer, db.ForeignKey("data_source.id"))
    source = db.relationship(
        "DataSource",
        foreign_keys=[source_id],
        backref=db.backref("annotations", lazy=True),
    )
    type = db.Column(db.Enum("alert", "holiday", "label", name="annotation_type"))
    __table_args__ = (
        db.UniqueConstraint(
            "content",
            "start",
            "source_id",
            "type",
            name="annotation_content_key",
        ),
    )

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def __repr__(self) -> str:
        return f"<Annotation {self.id}: {self.content} ({self.type}), start: {self.start} end: {self.end}, source: {self.source}>"


class AccountAnnotationRelationship(db.Model):
    """Links annotations to accounts."""

    __tablename__ = "annotations_accounts"

    id = db.Column(db.Integer(), primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"))
    annotation_id = db.Column(db.Integer, db.ForeignKey("annotation.id"))
    __table_args__ = (
        db.UniqueConstraint(
            "annotation_id",
            "account_id",
            name="annotations_accounts_annotation_id_key",
        ),
    )


class GenericAssetAnnotationRelationship(db.Model):
    """Links annotations to generic assets."""

    __tablename__ = "annotations_assets"

    id = db.Column(db.Integer(), primary_key=True)
    generic_asset_id = db.Column(db.Integer, db.ForeignKey("generic_asset.id"))
    annotation_id = db.Column(db.Integer, db.ForeignKey("annotation.id"))
    __table_args__ = (
        db.UniqueConstraint(
            "annotation_id",
            "generic_asset_id",
            name="annotations_assets_annotation_id_key",
        ),
    )


class SensorAnnotationRelationship(db.Model):
    """Links annotations to sensors."""

    __tablename__ = "annotations_sensors"

    id = db.Column(db.Integer(), primary_key=True)
    sensor_id = db.Column(db.Integer, db.ForeignKey("sensor.id"))
    annotation_id = db.Column(db.Integer, db.ForeignKey("annotation.id"))
    __table_args__ = (
        db.UniqueConstraint(
            "annotation_id",
            "sensor_id",
            name="annotations_sensors_annotation_id_key",
        ),
    )


def get_or_create_annotation(
    annotation: Annotation,
) -> Annotation:
    """Add annotation to db session if it doesn't exist in the session already.

    Return the old annotation object if it exists (and expunge the new one). Otherwise, return the new one.
    """
    with db.session.no_autoflush:
        existing_annotation = (
            db.session.query(Annotation)
            .filter(
                Annotation.content == annotation.content,
                Annotation.start == annotation.start,
                Annotation.end == annotation.end,
                Annotation.source == annotation.source,
                Annotation.type == annotation.type,
            )
            .one_or_none()
        )
    if existing_annotation is None:
        db.session.add(annotation)
        return annotation
    if annotation in db.session:
        db.session.expunge(annotation)
    return existing_annotation
