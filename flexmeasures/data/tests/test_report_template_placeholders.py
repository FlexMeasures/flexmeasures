"""Tests for describing and refusing the placeholders that report templates leave open."""

from __future__ import annotations

import pytest
from marshmallow import ValidationError

from flexmeasures.data.services.report_templates import (
    describe_placeholders,
    find_placeholders,
    get_report_template,
    list_report_templates,
    refuse_unfilled_placeholders,
)


def test_clipped_values_placeholders_are_told_apart_by_kind():
    """The bounds in the config take plain values, labelled by the template, and the input and output take sensors, each labelled by its name."""
    placeholders = describe_placeholders(get_report_template("clipped-values"))

    assert placeholders == [
        {
            "section": "config",
            "path": "transformations[0].kwargs.lower",
            "location": ["transformations", 0, "kwargs", "lower"],
            "kind": "value",
            "label": "Lowest valid value",
        },
        {
            "section": "config",
            "path": "transformations[0].kwargs.upper",
            "location": ["transformations", 0, "kwargs", "upper"],
            "kind": "value",
            "label": "Highest valid value",
        },
        {
            "section": "parameters",
            "path": "input[0].sensor",
            "location": ["input", 0, "sensor"],
            "kind": "sensor",
            "label": "Input sensor: measurements",
        },
        {
            "section": "parameters",
            "path": "output[0].sensor",
            "location": ["output", 0, "sensor"],
            "kind": "sensor",
            "label": "Output sensor: clipped",
        },
    ]


def test_a_sensor_in_the_config_is_a_sensor_placeholder():
    """The price sensor of the energy-costs template sits in the reporter config, under a key of its own."""
    placeholders = describe_placeholders(get_report_template("energy-costs"))

    assert {(p["section"], p["path"], p["kind"], p["label"]) for p in placeholders} == {
        ("config", "consumption_price_sensor", "sensor", "Consumption price sensor"),
        ("parameters", "input[0].sensor", "sensor", "Input sensor"),
        ("parameters", "output[0].sensor", "sensor", "Output sensor"),
    }


@pytest.mark.parametrize(
    "template", list_report_templates(), ids=lambda template: template["name"]
)
def test_every_placeholder_is_described_once(template):
    """Each template's placeholders are described exactly where `find_placeholders` finds them."""
    described = {(p["section"], p["path"]) for p in describe_placeholders(template)}
    found = {
        (section, path)
        for section in ("config", "parameters")
        for path in find_placeholders(template.get(section) or {})
    }
    assert described == found
    assert len(described) == len(describe_placeholders(template))


def test_unfilled_placeholders_are_refused_by_section():
    """Each unfilled placeholder is named under the part of the report definition it is in."""
    template = get_report_template("clipped-values")
    parameters = dict(
        template["parameters"], input=[{"name": "measurements", "sensor": 1}]
    )

    with pytest.raises(ValidationError) as exc_info:
        refuse_unfilled_placeholders(template["config"], parameters)

    assert exc_info.value.messages == {
        "config": [
            "Replace the 'FILL_IN' template placeholder at transformations[0].kwargs.lower.",
            "Replace the 'FILL_IN' template placeholder at transformations[0].kwargs.upper.",
        ],
        "parameters": [
            "Replace the 'FILL_IN' template placeholder at output[0].sensor.",
        ],
    }


def test_a_filled_in_definition_is_not_refused():
    refuse_unfilled_placeholders(
        {"method": "sum"}, {"input": [{"sensor": 1}], "output": [{"sensor": 2}]}
    )
    refuse_unfilled_placeholders(None, None)


@pytest.mark.parametrize(
    "template", list_report_templates(), ids=lambda template: template["name"]
)
def test_every_placeholder_has_a_label_that_says_what_to_fill_in(template):
    """A placeholder passed as a method's first argument would otherwise be labelled by its index, such as "0"."""
    for placeholder in describe_placeholders(template):
        label = placeholder["label"]
        assert (
            not label.strip().isdigit()
        ), f"{placeholder['path']} is labelled {label!r}"


def test_a_template_can_name_a_placeholder_label():
    """The bounds of the valid-range template are passed to `ge` and `le`, so the template names them."""
    labels = [
        p["label"] for p in describe_placeholders(get_report_template("valid-range"))
    ]
    assert labels[:2] == ["Lowest valid value", "Highest valid value"]


@pytest.mark.parametrize(
    "template", list_report_templates(), ids=lambda template: template["name"]
)
def test_every_template_has_a_short_summary_for_the_form(template):
    """The form shows the summary when hovering over a template, so it is there, and short enough to read at a glance."""
    summary = (template.get("form") or {}).get("summary")
    assert summary, f"{template['name']} has no form.summary"
    assert (
        len(summary) <= 90
    ), f"{template['name']}'s summary is {len(summary)} characters long"
