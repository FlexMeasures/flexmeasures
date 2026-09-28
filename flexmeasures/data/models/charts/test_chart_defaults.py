import json

import altair as alt

from flexmeasures.data.models.charts.defaults import (
    FIELD_DEFINITIONS,
    apply_chart_defaults,
)


def test_default_encodings():
    """Check default encodings for valid vega-lite specifications."""
    for field_name, field_definition in FIELD_DEFINITIONS.items():
        assert alt.PositionFieldDef(**field_definition)


def _single_chart_with_annotations() -> dict:
    """A single (not vertically concatenated) chart, as on the sensor page, with annotations."""
    specs = {
        "layer": [
            {
                "mark": "bar",
                "encoding": {
                    "x": {"field": "event_start", "timeUnit": {"step": 900}},
                },
            }
        ]
    }
    return apply_chart_defaults(specs)(dataset_name="d", include_annotations=True)


def test_single_chart_annotations_match_the_subchart_annotations():
    """A single chart shades hovered annotations a darker grey, as the subcharts of a vconcat chart do, rather than in the highlight colour."""
    specs = _single_chart_with_annotations()
    names = [layer.get("name") for layer in specs["layer"]]
    assert names == [
        "annotation_band_0",
        "annotation_rule_0",
        "annotation_marker_0",
        None,  # the chart itself
        "annotation_text_0",
    ]
    band = specs["layer"][0]
    assert band["data"] == {"name": "d_annotations"}
    assert band["encoding"]["color"]["value"] == "var(--gray)"
    assert "secondary" not in json.dumps(specs)
    # The instant-annotation hover tolerance is one event of the chart (15 minutes)
    assert "<= 900000" in json.dumps(specs["layer"][1]["encoding"]["opacity"])


def test_pinning_an_annotation_replaces_the_previous_pin():
    """Shift-click does not keep an earlier pinned annotation, as in the fast chart."""
    specs = _single_chart_with_annotations()
    pin = next(
        p for p in specs["layer"][0]["params"] if p["name"] == "annotation_pin_time_0"
    )
    assert pin["select"]["toggle"] is False
