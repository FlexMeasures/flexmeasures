from typing import Optional, Union

import timely_beliefs as tb
from flask import current_app

from flexmeasures.data.config import db
from flexmeasures.data.models.user import User, is_user


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
            self.user_id = user.id
        elif user is None and type == "user":
            raise TypeError("A data source cannot have type 'user' but no user set.")
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

    def __repr__(self):
        return "<Data source %r (%s)>" % (self.id, self.description)

    def __str__(self):
        return self.description


def get_or_create_source(
    source: Union[User, str], source_type: Optional[str] = None, flush: bool = True
) -> DataSource:
    if is_user(source):
        source_type = "user"
    query = DataSource.query.filter(DataSource.type == source_type)
    if is_user(source):
        query = query.filter(DataSource.user == source)
    elif isinstance(source, str):
        query = query.filter(DataSource.name == source)
    else:
        raise TypeError("source should be of type User or str")
    _source = query.one_or_none()
    if not _source:
        current_app.logger.info(f"Setting up '{source}' as new data source...")
        if is_user(source):
            _source = DataSource(user=source)
        else:
            if source_type is None:
                raise TypeError("Please specify a source type")
            _source = DataSource(name=source, type=source_type)
        db.session.add(_source)
        if flush:
            # assigns id so that we can reference the new object in the current db session
            db.session.flush()
    return _source


def get_source_or_none(source: int, source_type: str) -> Optional[DataSource]:
    query = DataSource.query.filter(DataSource.type == source_type)
    query = query.filter(DataSource.id == int(source))
    return query.one_or_none()
