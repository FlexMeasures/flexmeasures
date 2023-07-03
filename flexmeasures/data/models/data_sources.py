from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from sqlalchemy.ext.mutable import MutableDict

import timely_beliefs as tb

from flexmeasures.data import db
from flask import current_app
import hashlib

from marshmallow import Schema


if TYPE_CHECKING:
    from flexmeasures.data.models.user import User


class DataGenerator:
    __data_generator_base__: str | None = None
    _data_source: DataSource | None = None

    _config: dict = None

    _input_schema: Schema | None = None
    _config_schema: Schema | None = None

    def __init__(self, config: dict | None = None, **kwargs) -> None:
        """Base class for the Schedulers, Reporters and Forecasters.

        The configuration `config` stores static parameters, parameters that, if
        changed, trigger the creation of a new DataSource.  Dynamic parameters, such as
        the start date, can go into the `input`. See docstring of the method `DataGenerator.compute` for
        more details.


        Create a new DataGenerator with a certain configuration. There are two alternatives
        to define the parameters:

            1.  Serialized through the keyword argument `config`.
            2.  Deserialized, passing each parameter as keyword arguments.

        The configuration is validated using the schema `_config_schema`, to be defined.

        Example:

            The configuration requires the parameters start and end, two datetimes.

            Option 1:
            dg = DataGenerator(config = {
                "start" : "2023-01-01T00:00:00+00:00",
                "end" : "2023-01-02T00:00:00+00:00"
            })

            Option 2:
            df = DataGenerator(start = datetime(2023, 1, 1, tzinfo = UTC),
                               end = datetime(2023, 1, 2, tzinfo = UTC))


        :param config: serialized `config` parameters, defaults to None
        """

        if config is None:
            self._config = kwargs
            DataGenerator.validate_deserialized(self._config, self._config_schema)
        elif self._config_schema:
            self._config = self._config_schema.load(config)
        else:
            self._config = config

    def _compute(self, **kwargs):
        raise NotImplementedError()

    def compute(self, input: dict | None = None, **kwargs):
        """The configuration `input` stores dynamic parameters, parameters that, if
        changed, DO NOT trigger the creation of a new DataSource. Static parameters, such as
        the topology of an energy system, can go into `config`.

        :param input: serialized `input` parameters, defaults to None
        """
        if input is None:
            _input = kwargs
            DataGenerator.validate_deserialized(_input, self._input_schema)
        elif self._input_schema:
            _input = self._input_schema.load(input)
        else:  # skip validation
            _input = input

        return self._compute(**_input)

    @staticmethod
    def validate_deserialized(values: dict, schema: Schema) -> bool:
        schema.load(schema.dump(values))

    @classmethod
    def get_data_source_info(cls: type) -> dict:
        """
        Create and return the data source info, from which a data source lookup/creation is possible.

        See for instance get_data_source_for_job().
        """
        source_info = dict(
            source=current_app.config.get("FLEXMEASURES_DEFAULT_DATASOURCE")
        )  # default

        source_info["source_type"] = cls.__data_generator_base__
        source_info["model"] = cls.__name__

        return source_info

    @property
    def data_source(self) -> "DataSource" | None:
        from flexmeasures.data.services.data_sources import get_or_create_source

        if self._data_source is None:
            data_source_info = self.get_data_source_info()
            data_source_info["attributes"] = {
                "data_generator": {"config": self._config_schema.dump(self._config)}
            }

            self._data_source = get_or_create_source(**data_source_info)

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

    _data_generator: DataGenerator | None = None

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
    def data_generator(self):
        if self._data_generator:
            return self._data_generator

        data_generator = None

        if self.type not in ["scheduler", "forecaster", "reporter"]:
            raise NotImplementedError(
                "Only the classes Scheduler, Forecaster and Reporters are DataGenerator's."
            )

        if not self.model:
            raise NotImplementedError(
                "There's no DataGenerator class defined in this DataSource."
            )

        types = current_app.data_generators

        if all(
            [self.model not in current_app.data_generators[_type] for _type in types]
        ):
            raise NotImplementedError(
                "DataGenerator `{self.model}` not registered in this FlexMeasures instance."
            )

        # fetch DataGenerator details
        data_generator_details = self.attributes.get("data_generator", {})
        config = data_generator_details.get("config", {})

        # create DataGenerator class and assign the current DataSource (self) as its source
        data_generator = current_app.data_generators[self.type][self.model](
            config=config
        )
        data_generator._data_source = self

        self._data_generator = data_generator

        return self._data_generator

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
