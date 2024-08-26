from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar
from sqlalchemy.ext.mutable import MutableDict

import timely_beliefs as tb

from packaging.version import Version

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
    _parameters: dict = None

    _parameters_schema: Schema | None = None
    _config_schema: Schema | None = None
    _save_config: bool = True
    _save_parameters: bool = False

    def __init__(
        self,
        config: dict | None = None,
        save_config=True,
        save_parameters=False,
        **kwargs,
    ) -> None:
        """Base class for the Schedulers, Reporters and Forecasters.

        The configuration `config` stores static parameters, parameters that, if
        changed, trigger the creation of a new DataSource.  Dynamic parameters, such as
        the start date, can go into the `parameters`. See docstring of the method `DataGenerator.compute` for
        more details. Nevertheless, the parameter `save_parameters` can be set to True if some `parameters` need
        to be saved to the DB. In that case, the method `_clean_parameters` is called to remove any field that is not
        to be persisted, e.g. time parameters which are already contained in the TimedBelief.

        Create a new DataGenerator with a certain configuration. There are two alternatives
        to define the parameters:

            1.  Serialized through the keyword argument `config`.
            2.  Deserialized, passing each parameter as keyword arguments.

        The configuration is validated using the schema `_config_schema`, to be defined by the subclass.

        `config` cannot contain the key `config` at its top level, otherwise it could conflict with the constructor keyword argument `config`
        when passing the config as deserialized attributes.

        Example:

            The configuration requires two parameters for the PV and consumption sensors.

            Option 1:
                dg = DataGenerator(config = {
                    "sensor_pv" : 1,
                    "sensor_consumption" : 2
                })

            Option 2:
                sensor_pv = Sensor.query.get(1)
                sensor_consumption = Sensor.query.get(2)

                dg = DataGenerator(sensor_pv = sensor_pv,
                                sensor_consumption = sensor_consumption)


        :param config: serialized `config` parameters, defaults to None
        :param save_config: whether to save the config into the data source attributes
        :param save_parameters: whether to save the parameters into the data source attributes
        """

        self._save_config = save_config
        self._save_parameters = save_parameters

        if config is None and len(kwargs) > 0:
            self._config = kwargs
            DataGenerator.validate_deserialized(self._config, self._config_schema)
        elif config is not None:
            self._config = self._config_schema.load(config)
        elif len(kwargs) == 0:
            self._config = self._config_schema.load({})

    def _compute(self, **kwargs) -> list[dict[str, Any]]:
        raise NotImplementedError()

    def compute(self, parameters: dict | None = None, **kwargs) -> list[dict[str, Any]]:
        """The configuration `parameters` stores dynamic parameters, parameters that, if
        changed, DO NOT trigger the creation of a new DataSource. Static parameters, such as
        the topology of an energy system, can go into `config`.

        `parameters` cannot contain the key `parameters` at its top level, otherwise it could conflict with keyword argument `parameters`
        of the method compute when passing the `parameters` as deserialized attributes.

        :param parameters: serialized `parameters` parameters, defaults to None
        """

        if self._parameters is None:
            self._parameters = {}

        if parameters is None:
            self._parameters.update(self._parameters_schema.dump(kwargs))
        else:
            self._parameters.update(parameters)

        self._parameters = self._parameters_schema.load(self._parameters)

        return self._compute(**self._parameters)

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
    def data_source(self) -> "DataSource":
        """DataSource property derived from the `source_info`: `source_type` (scheduler, forecaster or reporter), `model` (e.g AggregatorReporter)
        and `attributes`. It looks for a data source in the database the marges the `source_info` and, in case of not finding any, it creates a new one.
        This property gets created once and it's cached for the rest of the lifetime of the DataGenerator object.
        """

        from flexmeasures.data.services.data_sources import get_or_create_source

        if self._data_source is None:
            data_source_info = self.get_data_source_info()

            attributes = {"data_generator": {}}

            if self._save_config:
                attributes["data_generator"]["config"] = self._config_schema.dump(
                    self._config
                )

            if self._save_parameters:
                attributes["data_generator"]["parameters"] = self._clean_parameters(
                    self._parameters_schema.dump(self._parameters)
                )

            data_source_info["attributes"] = attributes

            self._data_source = get_or_create_source(**data_source_info)

        return self._data_source

    def _clean_parameters(self, parameters: dict) -> dict:
        """Use this function to clean up the parameters dictionary from the
        fields that are not to be persisted to the DB as data source attributes (when save_parameters=True),
        e.g. because they are already stored as TimedBelief properties, or otherwise.

        Example:

            An DataGenerator has the following parameters: ["start", "end", "field1", "field2"] and we want just "field1" and "field2"
            to be persisted.

            Parameters provided to the `compute` method (input of the method `_clean_parameters`):
            parameters = {
                            "start" : "2023-01-01T00:00:00+02:00",
                            "end" : "2023-01-02T00:00:00+02:00",
                            "field1" : 1,
                            "field2" : 2
                        }

            Parameters persisted to the DB (output of the method `_clean_parameters`):
            parameters = {"field1" : 1,"field2" : 2}
        """

        raise NotImplementedError()


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

    _data_generator: ClassVar[DataGenerator | None] = None

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
    def data_generator(self) -> DataGenerator:
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
        parameters = data_generator_details.get("parameters", {})

        # create DataGenerator class and add the parameters
        data_generator = current_app.data_generators[self.type][self.model](
            config=config
        )
        data_generator._parameters = parameters

        # assign the current DataSource (self) as its source
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


def keep_latest_version(data_sources: list[DataSource]) -> list[DataSource]:
    """
    Filters the given list of data sources to only include the latest version
    of each unique combination of (name, type, and model).
    """
    sources = dict()

    for source in data_sources:
        key = (source.name, source.type, source.model)
        if key not in sources:
            sources[key] = source
        else:
            sources[key] = max(
                [source, sources[key]],
                key=lambda x: Version(x.version if x.version else "0.0.0"),
            )

    last_version_sources = []
    for source in sources.values():
        last_version_sources.append(source)

    return last_version_sources
