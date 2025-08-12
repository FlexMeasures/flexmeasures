from __future__ import annotations

from datetime import timedelta

import pandas as pd
from sqlalchemy import select

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
    start = db.Column(db.DateTime(timezone=True), nullable=False)
    end = db.Column(db.DateTime(timezone=True), nullable=False)
    belief_time = db.Column(db.DateTime(timezone=True), nullable=True)
    source_id = db.Column(db.Integer, db.ForeignKey("data_source.id"), nullable=False)
    source = db.relationship(
        "DataSource",
        foreign_keys=[source_id],
        backref=db.backref("annotations", lazy=True),
    )
    type = db.Column(
        db.Enum(
            "alert",
            "holiday",
            "label",
            "feedback",
            "warning",
            "error",
            name="annotation_type",
        ),
        nullable=False,
    )
    content = db.Column(db.String(1024), nullable=False)
    __table_args__ = (
        db.UniqueConstraint(
            "content",
            "start",
            "belief_time",
            "source_id",
            "type",
            name="annotation_content_key",
        ),
    )

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    @classmethod
    def add(
        cls,
        df: pd.DataFrame,
        annotation_type: str,
        expunge_session: bool = False,
        allow_overwrite: bool = False,
        bulk_save_objects: bool = False,
        commit_transaction: bool = False,
    ) -> list["Annotation"]:
        """Add a data frame describing annotations to the database and return the Annotation objects.

        :param df:                  Data frame describing annotations.
                                    Expects the following columns (or multi-index levels):
                                    - start
                                    - end or duration
                                    - content
                                    - belief_time
                                    - source
        :param annotation_type:     One of the possible Enum values for annotation.type
        :param expunge_session:     if True, all non-flushed instances are removed from the session before adding annotations.
                                    Expunging can resolve problems you might encounter with states of objects in your session.
                                    When using this option, you might want to flush newly-created objects which are not annotations
                                    (e.g. a sensor or data source object).
        :param allow_overwrite:     if True, new objects are merged
                                    if False, objects are added to the session or bulk saved
        :param bulk_save_objects:   if True, objects are bulk saved with session.bulk_save_objects(),
                                    which is quite fast but has several caveats, see:
                                    https://docs.sqlalchemy.org/orm/persistence_techniques.html#bulk-operations-caveats
                                    if False, objects are added to the session with session.add_all()
        :param commit_transaction:  if True, the session is committed
                                    if False, you can still add other data to the session
                                    and commit it all within an atomic transaction
        """
        df = df.reset_index()
        starts = df["start"]
        if "end" in df.columns:
            ends = df["end"]
        elif "start" in df.columns and "duration" in df.columns:
            ends = df["start"] + df["duration"]
        else:
            raise ValueError(
                "Missing 'end' column cannot be derived from columns 'start' and 'duration'."
            )
        values = df["content"]
        belief_times = df["belief_time"]
        sources = df["source"]
        annotations = [
            cls(
                content=row[0],
                start=row[1],
                end=row[2],
                belief_time=row[3],
                source=row[4],
                type=annotation_type,
            )
            for row in zip(values, starts, ends, belief_times, sources)
        ]

        # Deal with the database session
        if expunge_session:
            db.session.expunge_all()
        if not allow_overwrite:
            if bulk_save_objects:
                db.session.bulk_save_objects(annotations)
            else:
                db.session.add_all(annotations)
        else:
            for annotation in annotations:
                db.session.merge(annotation)
        if commit_transaction:
            db.session.commit()

        return annotations

    def __repr__(self) -> str:
        return f"<Annotation {self.id}: {self.content} ({self.type}), start: {self.start} end: {self.end}, source: {self.source}>"


class AccountAnnotationRelationship(db.Model):
    """Links annotations to accounts."""

    __tablename__ = "annotations_accounts"

    id = db.Column(db.Integer(), primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id", ondelete="CASCADE"))
    annotation_id = db.Column(
        db.Integer, db.ForeignKey("annotation.id", ondelete="CASCADE")
    )
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
    generic_asset_id = db.Column(
        db.Integer, db.ForeignKey("generic_asset.id", ondelete="CASCADE")
    )
    annotation_id = db.Column(
        db.Integer, db.ForeignKey("annotation.id", ondelete="CASCADE")
    )
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
    sensor_id = db.Column(db.Integer, db.ForeignKey("sensor.id", ondelete="CASCADE"))
    annotation_id = db.Column(
        db.Integer, db.ForeignKey("annotation.id", ondelete="CASCADE")
    )
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
        existing_annotation = db.session.execute(
            select(Annotation).filter(
                Annotation.content == annotation.content,
                Annotation.start == annotation.start,
                Annotation.end == annotation.end,
                Annotation.source == annotation.source,
                Annotation.type == annotation.type,
            )
        ).scalar_one_or_none()
    if existing_annotation is None:
        db.session.add(annotation)
        return annotation
    if annotation in db.session:
        db.session.expunge(annotation)
    return existing_annotation


def to_annotation_frame(annotations: list[Annotation]) -> pd.DataFrame:
    """Transform a list of annotations into a DataFrame.

    We don't use a BeliefsDataFrame here, because they are designed for quantitative data only.
    """
    return pd.DataFrame(
        [
            [a.start, a.end, a.belief_time, a.source, a.type, a.content]
            for a in annotations
        ],
        columns=["start", "end", "belief_time", "source", "type", "content"],
    )
