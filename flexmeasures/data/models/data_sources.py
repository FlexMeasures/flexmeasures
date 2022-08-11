from __future__ import annotations
from typing import Optional, TYPE_CHECKING

import timely_beliefs as tb

from flexmeasures.data import db

if TYPE_CHECKING:
    from flexmeasures.data.models.user import User


class DataSource(db.Model, tb.BeliefSourceDBMixin):
    """Each data source is a data-providing entity."""

    __tablename__ = "data_source"
    __table_args__ = (db.UniqueConstraint("name", "user_id", "model", "version"),)

    # The type of data source (e.g. user, forecasting script or scheduling script)
    type = db.Column(db.String(80), default="")

    # The id of the user source (can link e.g. to fm_user table)
    user_id = db.Column(
        db.Integer, db.ForeignKey("fm_user.id"), nullable=True, unique=True
    )
    user = db.relationship("User", backref=db.backref("data_source", lazy=True))

    # The model and version of a script source
    model = db.Column(db.String(80), nullable=True)
    version = db.Column(
        db.String(17),  # length supports up to version 999.999.999dev999
        nullable=True,
    )

    def __init__(
        self,
        name: Optional[str] = None,
        type: Optional[str] = None,
        user: Optional[User] = None,
        **kwargs,
    ):
        if user is not None:
            name = user.username
            type = "user"
            self.user = user
        elif user is None and type == "user":
            raise TypeError("A data source cannot have type 'user' but no user set.")
        self.type = type
        tb.BeliefSourceDBMixin.__init__(self, name=name)
        db.Model.__init__(self, **kwargs)

    @property
    def label(self):
        """Human-readable label (preferably not starting with a capital letter so it can be used in a sentence)."""
        if self.type == "user":
            return f"data entered by user {self.user.username}"  # todo: give users a display name
        elif self.type == "forecasting script":
            return f"forecast by {self.name}"  # todo: give DataSource an optional db column to persist versioned models separately to the name of the data source?
        elif self.type == "scheduling script":
            return f"schedule by {self.name}"
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

            >>> DataSource("Seita", type="forecasting script", model="naive", version="1.2").description
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
            model_incl_version += f" ({self.version}"
        return dict(
            id=self.id,
            name=self.name,
            model=model_incl_version,
            description=self.description,
        )
