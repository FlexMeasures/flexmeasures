"""Registered automation handlers and the worker for plugin data generators."""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from datetime import timedelta
import re

from flask import current_app
from marshmallow import RAISE, ValidationError, Schema
from rq.job import Job
from packaging.version import Version
from werkzeug.exceptions import Forbidden

from flexmeasures.data import db
from flexmeasures.data.models.data_sources import DataGenerator
from flexmeasures.utils.job_utils import KNOWN_JOB_QUEUES


class AutomationPayloadValidationError(ValidationError):
    """A plugin payload error that identifies configuration versus run parameters."""


def load_automation_payload(schema: Schema, payload: dict, field: str) -> dict:
    """Load a strict plugin schema and retain the payload's field in errors."""
    try:
        return schema.load(payload, unknown=RAISE)
    except ValidationError as exc:
        raise AutomationPayloadValidationError({field: exc.messages}) from exc


@dataclass(frozen=True)
class AutomationHandler:
    """Declare a type backed by a generator with configuration and parameter schemas.

    Plugins expose instances in ``__automation_types__``. Generator sensor properties
    must enumerate every sensor read or written by the computation. Credentials belong
    in server settings, never configuration or parameters persisted by this handler.
    """

    type_id: str
    display_name: str
    generator_class: type[DataGenerator] | None = None
    queue: str = "ingestion"
    result_noun: str = "result"

    def create(self, **kwargs):
        """Validate and create the automation without committing it."""
        from flexmeasures.data.models.automations import Automation
        from flexmeasures.data.models.audit_log import AssetAuditLog
        from flexmeasures.data.services.data_generators import (
            check_sensor_access,
            resolve_data_generator_sensors,
        )
        from flexmeasures.data.services.automations import _create_builtin_automation

        if self.generator_class is None:
            kwargs["generator_class"] = (
                kwargs.get("generator_class") or "TrainPredictPipeline"
            )
            return _create_builtin_automation(**kwargs)
        selected_class = kwargs.get("generator_class")
        if selected_class not in (
            None,
            "TrainPredictPipeline",
            self.generator_class.__name__,
        ):
            raise ValidationError("This automation type determines its data generator.")
        asset = kwargs["asset"]
        source = kwargs.get("source")
        if source is not None:
            load_automation_payload(
                self.generator_class._config_schema,
                source.attributes.get("data_generator", {}).get("config", {}),
                "config",
            )
            generator = copy(source.data_generator)
            if type(generator) is not self.generator_class:
                raise ValidationError(
                    "The source does not belong to this automation type."
                )
            if kwargs.get("config"):
                raise ValidationError("Use either a source or configuration, not both.")
        else:
            config = load_automation_payload(
                self.generator_class._config_schema,
                kwargs.get("config") or {},
                "config",
            )
            generator = self.generator_class(
                config=self.generator_class._config_schema.dump(config)
            )
        parameters = kwargs.get("parameters") or {}
        loaded = load_automation_payload(
            generator._parameters_schema, parameters, "parameters"
        )
        sensors = resolve_data_generator_sensors(generator, loaded)
        if kwargs.get("check_permissions"):
            check_sensor_access(**sensors)
        validate_output_scope(asset.id, sensors["output_sensors"])
        if source is None:
            from flexmeasures.data.services.data_sources import get_or_create_source

            source_info = generator.get_data_source_info()
            source_info["version"] = str(
                Version(str(getattr(self.generator_class, "__version__", "0.1")))
            )
            source_info["attributes"] = {
                "data_generator": {
                    "config": generator._config_schema.dump(generator._config)
                }
            }
            generator._data_source = get_or_create_source(**source_info)
        automation = Automation(
            asset_id=asset.id,
            type=self.type_id,
            name=kwargs["name"],
            cronstr=kwargs["cronstr"],
            active=kwargs.get("active", True),
            generator=generator.data_source,
            parameters=parameters,
        )
        if kwargs.get("timezone") is not None:
            automation.timezone = kwargs["timezone"]
        else:
            from flexmeasures.data.models.automations import (
                get_default_automation_timezone,
            )

            automation.timezone = get_default_automation_timezone(asset)
        db.session.add(automation)
        db.session.flush()
        AssetAuditLog.add_record(
            asset,
            f"Created automation '{automation.name}' ({automation.id}) via {kwargs.get('origin', 'API')}.",
        )
        return automation, []

    def run(self, automation):
        """Queue work using only registered code and committed identifiers."""
        if self.generator_class is None:
            from flexmeasures.data.services.automations import (
                _run_forecast_automation,
                _run_schedule_automation,
            )

            runner = {
                "forecasting": _run_forecast_automation,
                "scheduling": _run_schedule_automation,
            }[self.type_id]
            return runner(automation)
        generator, sensors = resolve_plugin_generator(automation, self)
        validate_output_scope(automation.asset_id, sensors["output_sensors"])
        source_id = generator.data_source.id
        parameters = dict(automation.parameters or {})
        db.session.commit()
        queue = current_app.queues[self.queue]
        job = Job.create(
            execute_automation_job,
            kwargs={
                "automation_id": automation.id,
                "data_source_id": source_id,
                "parameters": parameters,
            },
            connection=queue.connection,
            timeout=queue._default_timeout,
            ttl=int(
                current_app.config.get(
                    "FLEXMEASURES_JOB_TTL", timedelta(-1)
                ).total_seconds()
            ),
            result_ttl=int(
                current_app.config.get(
                    "FLEXMEASURES_PLANNING_TTL", timedelta(-1)
                ).total_seconds()
            ),
            meta={
                "trigger": {"origin": "automation", "automation_id": automation.id},
                "data_source_info": {"id": source_id},
                "asset_id": automation.asset_id,
                "asset_or_sensor": {"class": "Asset", "id": automation.asset_id},
            },
        )
        queue.enqueue_job(job)
        current_app.job_cache.add(
            automation.asset_id,
            job_id=job.id,
            queue=self.queue,
            asset_or_sensor_type="asset",
        )
        return {"job_id": job.id, "n_jobs": 1}


def initialize_automation_handlers(app):
    """Install built-in handlers in this application's registry."""
    app.automation_handlers = {
        "forecasting": AutomationHandler(
            "forecasting", "Forecasts", queue="forecasting", result_noun="forecast"
        ),
        "scheduling": AutomationHandler(
            "scheduling", "Schedules", queue="scheduling", result_noun="schedule"
        ),
    }


def register_automation_handler(app, handler: AutomationHandler):
    """Register trusted plugin code, rejecting ambiguous types and generators."""
    if not isinstance(handler, AutomationHandler):
        raise TypeError("Automation registrations must be AutomationHandler instances.")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", handler.type_id):
        raise ValueError(
            "Automation type identifiers must be lowercase letters, digits, underscores or hyphens, starting with a letter (maximum 80 characters)."
        )
    if handler.type_id in app.automation_handlers:
        raise ValueError(f"Automation type '{handler.type_id}' is already registered.")
    if handler.queue not in KNOWN_JOB_QUEUES:
        raise ValueError(f"Unknown automation queue '{handler.queue}'.")
    cls = handler.generator_class
    if (
        cls is None
        or not issubclass(cls, DataGenerator)
        or not cls.__data_generator_base__
    ):
        raise ValueError(
            "A plugin automation must declare a DataGenerator class and its __data_generator_base__."
        )
    if cls._config_schema is None or cls._parameters_schema is None:
        raise ValueError(
            "Automation generators must declare configuration and parameter schemas."
        )
    version = str(Version(str(getattr(cls, "__version__", "0.1"))))
    if (
        len(version) > 17
        or len(cls.__name__) > 80
        or len(cls.__data_generator_base__) > 80
    ):
        raise ValueError("Generator identity exceeds the DataSource storage limits.")
    registry = app.data_generators.setdefault(cls.__data_generator_base__, {})
    if cls.__name__ in registry and registry[cls.__name__] is not cls:
        raise ValueError(f"Data generator '{cls.__name__}' is already registered.")
    registry[cls.__name__] = cls
    app.automation_handlers[handler.type_id] = handler


def get_automation_types() -> dict[str, AutomationHandler]:
    """Return the handlers available in this application."""
    return current_app.automation_handlers


def get_automation_handler(type_id: str) -> AutomationHandler:
    """Resolve a trusted handler, failing safely when its plugin is unavailable."""
    try:
        return get_automation_types()[type_id]
    except KeyError as exc:
        raise NotImplementedError(
            f"Automation type '{type_id}' is unavailable. Install or enable its plugin on the server and worker."
        ) from exc


def validate_automation_type(type_id: str):
    """Validate creation against the current registry, not a static type list."""
    if type_id not in get_automation_types():
        raise ValidationError(
            f"Automation type '{type_id}' is not supported (supported types: {list(get_automation_types())})."
        )


def validate_output_scope(asset_id, sensors):
    """Require plugin results to stay within the automation's asset subtree."""
    from flexmeasures.data.queries.generic_assets import asset_is_in_subtree

    for sensor in sensors:
        if not asset_is_in_subtree(asset_id, sensor.generic_asset_id):
            raise ValueError(
                f"Automation output sensor {sensor.id} must belong to asset {asset_id} or one of its descendants."
            )


def resolve_plugin_generator(automation, handler, parameters=None):
    """Resolve the declared generator and sensors without sharing mutable run state."""
    from flexmeasures.data.services.data_generators import (
        resolve_data_generator_sensors,
    )

    if automation.generator is None:
        raise ValueError(f"Automation {automation.id} has no data source to run.")
    installed_version = str(
        Version(str(getattr(handler.generator_class, "__version__", "0.1")))
    )
    if automation.generator.version != installed_version:
        raise ValueError(
            f"Automation {automation.id} uses generator version {automation.generator.version},"
            f" but version {installed_version} is installed. Recreate the automation with the installed plugin version."
        )
    generator = copy(automation.generator.data_generator)
    if type(generator) is not handler.generator_class:
        raise ValueError(
            f"Data source {automation.generator_id} does not belong to automation type '{automation.type}'."
        )
    generator._parameters = None
    loaded = generator._parameters_schema.load(
        dict(automation.parameters or {}) if parameters is None else parameters,
        unknown=RAISE,
    )
    return generator, resolve_data_generator_sensors(generator, loaded)


def check_execution_access(automation, sensors):
    """Recheck the API creator's current permissions for unattended execution.

    A null identity denotes trusted CLI creation or a legacy automation. A deleted
    identity remains stored and fails closed, rather than reverting to CLI trust.
    """
    from flexmeasures.auth.policy import user_has_admin_access, user_matches_principals
    from flexmeasures.data.models.user import User

    if automation.execution_user_id is None:
        return
    user = db.session.get(User, automation.execution_user_id, populate_existing=True)
    if user is None or not user.active:
        raise Forbidden(
            "The automation's creating user is missing or inactive. Recreate it with an active user."
        )
    for entities, permission in (
        ([automation.asset], "read"),
        (sensors["input_sensors"], "read"),
        (sensors["output_sensors"], "create-children"),
    ):
        for entity in entities:
            if not user_has_admin_access(
                user, permission
            ) and not user_matches_principals(
                user, entity.__acl__().get(permission, [])
            ):
                raise Forbidden(
                    f"Automation {automation.id} creator no longer has '{permission}' permission on {entity}."
                )


def execute_automation_job(automation_id: int, data_source_id: int, parameters: dict):
    """Compute and persist declared results with provenance in a plugin-enabled worker."""
    from flexmeasures.data.models.automations import Automation
    from flexmeasures.data.utils import save_to_db

    automation = db.session.get(Automation, automation_id, populate_existing=True)
    if automation is None:
        raise ValueError(f"Automation {automation_id} is missing.")
    handler = get_automation_handler(automation.type)
    if (
        automation.generator_id != data_source_id
        or dict(automation.parameters) != parameters
    ):
        raise ValueError(
            "The automation changed after its job was queued. Queue a new run."
        )
    generator, sensors = resolve_plugin_generator(automation, handler, parameters)
    validate_output_scope(automation.asset_id, sensors["output_sensors"])
    check_execution_access(automation, sensors)
    output_ids = {sensor.id for sensor in sensors["output_sensors"]}
    results = generator.compute(parameters=parameters)
    # Validate every result before saving any, so undeclared outputs cannot be persisted.
    for result in results:
        if result["sensor"].id not in output_ids:
            raise Forbidden(
                f"The generator returned undeclared output sensor {result['sensor'].id}."
            )
    saved = []
    for result in results:
        save_to_db(result["data"])
        saved.append({"sensor_id": result["sensor"].id, "n_rows": len(result["data"])})
    db.session.commit()
    return saved
