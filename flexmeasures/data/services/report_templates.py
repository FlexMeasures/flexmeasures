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
