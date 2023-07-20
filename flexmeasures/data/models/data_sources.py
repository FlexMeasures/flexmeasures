from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from sqlalchemy.ext.mutable import MutableDict

import timely_beliefs as tb

from flexmeasures.data import db
from flask import current_app
import hashlib


if TYPE_CHECKING:
    from flexmeasures.data.models.user import User


class DataGeneratorMixin:
    _data_source: DataSource | None = None

    @classmethod
    def get_data_source_info(cls: type) -> dict:
        """
        Create and return the data source info, from which a data source lookup/creation is possible.

        See for instance get_data_source_for_job().
        """
        source_info = dict(
            name=current_app.config.get("FLEXMEASURES_DEFAULT_DATASOURCE")
        )  # default

        from flexmeasures.data.models.planning import Scheduler
        from flexmeasures.data.models.reporting import Reporter

        if issubclass(cls, Reporter):
            source_info["type"] = "reporter"
        elif issubclass(cls, Scheduler):
            source_info["type"] = "scheduler"
        else:
            source_info["type"] = "undefined"

        return source_info

    @property
    def data_source(self):
        from flexmeasures.data.services.data_sources import get_or_create_source

        if self._data_source is None:
            data_source_info = self.get_data_source_info()

            self._data_source = get_or_create_source(
                source=data_source_info.get("name"),
                source_type=data_source_info.get("type"),
            )

        return self._data_source


class DataSource(db.Model, tb.BeliefSourceDBMixin):
    """Each data source is a data-providing entity."""

    __tablename__ = "data_source"
    __table_args__ = (
        db.UniqueConstraint("name", "user_id", "model", "version", "attributes_hash"),
    )

    # The type of data source (e.g. user, forecaster or scheduler)
    type = db.Column(db.String(80), default="")

    # The id of the user source (can link e.g. to fm_user table)
    user_id = db.Column(
        db.Integer, db.ForeignKey("fm_user.id"), nullable=True, unique=True
    )
    user = db.relationship("User", backref=db.backref("data_source", lazy=True))

    attributes = db.Column(MutableDict.as_mutable(db.JSON), nullable=False, default={})

    attributes_hash = db.Column(db.LargeBinary(length=256))

    # The model and version of a script source
    model = db.Column(db.String(80), nullable=True)
    version = db.Column(
        db.String(17),  # length supports up to version 999.999.999dev999
        nullable=True,
    )

    sensors = db.relationship(
        "Sensor",
        secondary="timed_belief",
        backref=db.backref("data_sources", lazy="select"),
        viewonly=True,
    )

    def __init__(
        self,
        name: str | None = None,
        type: str | None = None,
        user: User | None = None,
        attributes: dict | None = None,
        **kwargs,
    ):
        if user is not None:
            name = user.username
            type = "user"
            self.user = user
        elif user is None and type == "user":
            raise TypeError("A data source cannot have type 'user' but no user set.")
        self.type = type

        if attributes is not None:
            self.attributes = attributes
            self.attributes_hash = hashlib.sha256(
                json.dumps(attributes).encode("utf-8")
            ).digest()

        tb.BeliefSourceDBMixin.__init__(self, name=name)
        db.Model.__init__(self, **kwargs)

    @property
    def label(self):
        """Human-readable label (preferably not starting with a capital letter, so it can be used in a sentence)."""
        if self.type == "user":
            return f"data entered by user {self.user.username}"  # todo: give users a display name
        elif self.type == "forecaster":
            return f"forecast by {self.name}"  # todo: give DataSource an optional db column to persist versioned models separately to the name of the data source?
        elif self.type == "scheduler":
            return f"schedule by {self.name}"
        elif self.type == "reporter":
            return f"report by {self.name}"
        elif self.type == "crawling script":
            return f"data retrieved from {self.name}"
        elif self.type in ("demo script", "CLI script"):
            return f"demo data entered by {self.name}"
        else:
            return f"data from {self.name}"

    @property
    def description(self):
        """Extended description

        For example:

            >>> DataSource("Seita", type="forecaster", model="naive", version="1.2").description
            <<< "Seita's naive model v1.2.0"

        """
        descr = self.name
        if self.model:
            descr += f"'s {self.model} model"
            if self.version:
                descr += f" v{self.version}"
        return descr

    def __repr__(self) -> str:
        return "<Data source %r (%s)>" % (self.id, self.description)

    def __str__(self) -> str:
        return self.description

    def to_dict(self) -> dict:
        model_incl_version = self.model if self.model else ""
        if self.model and self.version:
            model_incl_version += f" (v{self.version})"
        return dict(
            id=self.id,
            name=self.name,
            model=model_incl_version,
            type=self.type if self.type in ("forecaster", "scheduler") else "other",
            description=self.description,
        )

    @staticmethod
    def hash_attributes(attributes: dict) -> str:
        return hashlib.sha256(json.dumps(attributes).encode("utf-8")).digest()

    def get_attribute(self, attribute: str, default: Any = None) -> Any:
        """Looks for the attribute in the DataSource's attributes column."""
        return self.attributes.get(attribute, default)

    def has_attribute(self, attribute: str) -> bool:
        return attribute in self.attributes

    def set_attribute(self, attribute: str, value):
        self.attributes[attribute] = value
