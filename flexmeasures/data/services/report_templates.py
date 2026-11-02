"""
Logic for loading prepared report templates.

Report templates are YAML files packaged in flexmeasures/data/templates/reports.
Each template describes a ready-made report definition: a reporter class,
a complete reporter config and a parameters skeleton in which users fill in
their own sensors (replacing the FILL_IN placeholders).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from marshmallow import ValidationError
import yaml

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "reports"

# Placeholder value users need to replace (usually with one of their sensor IDs)
PLACEHOLDER = "FILL_IN"

# Fields (within report parameters) that determine the reporting window
TIMING_FIELDS = ("start", "end", "start-offset", "end-offset")


def _template_paths() -> list[Path]:
    return sorted(TEMPLATES_DIR.glob("*.y*ml"))


def _template_path(name: str) -> Path | None:
    for path in _template_paths():
        if path.stem == name:
            return path
    return None


def list_report_templates() -> list[dict]:
    """Load all packaged report templates (sorted by name)."""
    return [yaml.safe_load(path.read_text()) for path in _template_paths()]


def get_report_template(name: str) -> dict | None:
    """Load the packaged report template with the given name, if it exists."""
    path = _template_path(name)
    if path is None:
        return None
    return yaml.safe_load(path.read_text())


def get_report_template_text(name: str) -> str | None:
    """The raw YAML of the packaged report template with the given name, if it exists.

    Unlike `get_report_template`, this preserves the explanatory comments,
    so users can pipe the result to a file and edit it.
    """
    path = _template_path(name)
    if path is None:
        return None
    return path.read_text()


def merge_template_parameters(
    template_parameters: dict,
    user_parameters: dict,
    user_provided_timing: bool = False,
) -> dict:
    """Merge user-provided report parameters on top of a template's parameters skeleton.

    Top-level keys provided by the user win. Timing fields are treated as a group:
    if the user provides any timing field (or `user_provided_timing` is set, e.g.
    because timing was given through CLI options), the template's recommended
    timing fields are dropped altogether.
    """
    merged = dict(template_parameters)
    if user_provided_timing or any(field in user_parameters for field in TIMING_FIELDS):
        for field in TIMING_FIELDS:
            merged.pop(field, None)
    merged.update(user_parameters)
    return merged


def find_placeholders(obj: Any, root: str = "") -> list[str]:
    """List the paths of any unfilled template placeholders in the given (nested) object."""
    paths: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            paths += find_placeholders(v, f"{root}.{k}" if root else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            paths += find_placeholders(v, f"{root}[{i}]")
    elif isinstance(obj, str) and obj == PLACEHOLDER:
        paths.append(root)
    return paths


def _placeholder_locations(obj: Any, location: tuple = ()) -> list[tuple]:
    """List where each unfilled placeholder sits in the given (nested) object, as the keys and indexes leading to it."""
    if isinstance(obj, dict):
        return [
            loc
            for k, v in obj.items()
            for loc in _placeholder_locations(v, location + (k,))
        ]
    if isinstance(obj, list):
        return [
            loc
            for i, v in enumerate(obj)
            for loc in _placeholder_locations(v, location + (i,))
        ]
    if isinstance(obj, str) and obj == PLACEHOLDER:
        return [location]
    return []


def _location_path(location: tuple) -> str:
    """Spell a location the way `find_placeholders` does, such as ``input[0].sensor``."""
    path = ""
    for step in location:
        path += (
            f"[{step}]"
            if isinstance(step, int)
            else (f".{step}" if path else str(step))
        )
    return path


def _is_sensor_key(key: Any) -> bool:
    """Whether a placeholder under this key takes a sensor ID, as ``sensor`` and ``consumption_price_sensor`` do."""
    return isinstance(key, str) and (
        key == "sensor" or key.endswith(("_sensor", "-sensor"))
    )


def _placeholder_label(section_content: dict, location: tuple) -> str:
    """A short label for a placeholder, for a form to put next to the field filling it in.

    A sensor in an input or output description is labelled by that description's name, such as ``Input sensor: production``,
    and any other placeholder by its own key, such as ``Lower`` or ``Consumption price sensor``.
    """
    key = location[-1]
    parent = section_content
    for step in location[:-1]:
        parent = parent[step]
    if key == "sensor" and len(location) >= 3 and location[0] in ("input", "output"):
        label = f"{str(location[0]).capitalize()} sensor"
        name = parent.get("name") if isinstance(parent, dict) else None
        return f"{label}: {name}" if name else label
    return str(key).replace("_", " ").replace("-", " ").capitalize()


def describe_placeholders(template: dict) -> list[dict]:
    """Describe each placeholder a report template leaves open, so that a form can offer one field per placeholder.

    Each description says which part of the template it is in (``config`` or ``parameters``),
    where in that part it sits (as a path and as the list of keys and indexes leading to it),
    whether it takes a sensor ID (``kind`` is ``sensor``) or another value (``kind`` is ``value``),
    and a label for the field.
    """
    descriptions = []
    for section in ("config", "parameters"):
        content = template.get(section) or {}
        for location in _placeholder_locations(content):
            descriptions.append(
                {
                    "section": section,
                    "path": _location_path(location),
                    "location": list(location),
                    "kind": "sensor" if _is_sensor_key(location[-1]) else "value",
                    "label": _placeholder_label(content, location),
                }
            )
    return descriptions


def refuse_unfilled_placeholders(config: dict | None, parameters: dict | None) -> None:
    """Refuse a report definition in which any template placeholder is still unfilled.

    A placeholder left in would fail every run, or be computed with as if it were a value, without saying which value was left out.

    :raises marshmallow.ValidationError: naming each unfilled placeholder, under the part of the definition it is in.
    """
    errors = {}
    for section, content in (("config", config), ("parameters", parameters)):
        paths = find_placeholders(content or {})
        if paths:
            errors[section] = [
                f"Replace the '{PLACEHOLDER}' template placeholder at {path}."
                for path in paths
            ]
    if errors:
        raise ValidationError(errors)
