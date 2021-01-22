from typing import Optional

import timely_beliefs as tb

from flexmeasures.data.config import db
from flexmeasures.data.models.user import User


class DataSource(db.Model, tb.BeliefSourceDBMixin):
    """Each data source is a data-providing entity."""

    __tablename__ = "data_source"

    # The type of data source (e.g. user, forecasting script or scheduling script)
    type = db.Column(db.String(80), default="")
    # The id of the source (can link e.g. to fm_user table)
    user_id = db.Column(
        db.Integer, db.ForeignKey("fm_user.id"), nullable=True, unique=True
    )

    user = db.relationship("User", backref=db.backref("data_source", lazy=True))

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
            self.user_id = user.id
        self.type = type
        tb.BeliefSourceDBMixin.__init__(self, name=name)
        db.Model.__init__(self, **kwargs)

    @property
    def label(self):
        """ Human-readable label (preferably not starting with a capital letter so it can be used in a sentence). """
        if self.type == "user":
            return f"data entered by user {self.user.username}"  # todo: give users a display name
        elif self.type == "forecasting script":
            return f"forecast by {self.name}"  # todo: give DataSource an optional db column to persist versioned models separately to the name of the data source?
        elif self.type == "scheduling script":
            return f"schedule by {self.name}"
        elif self.type == "crawling script":
            return f"data retrieved from {self.name}"
        elif self.type == "demo script":
            return f"demo data entered by {self.name}"
        else:
            return f"data from {self.name}"

    def __repr__(self):
        return "<Data source %r (%s)>" % (self.id, self.label)
