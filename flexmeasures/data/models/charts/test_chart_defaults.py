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


def _single_chart_with_annotations(step: float = 900) -> dict:
    """A single (not vertically concatenated) chart, as on the sensor page, with annotations."""
    specs = {
        "layer": [
            {
                "mark": "bar",
                "encoding": {
                    "x": {"field": "event_start", "timeUnit": {"step": step}},
                },
            }
        ]
    }
    return apply_chart_defaults(specs)(dataset_name="d", include_annotations=True)


def test_single_chart_annotations_match_the_subchart_annotations():
    """A single chart gets the annotation layers of a vconcat subchart."""
    specs = _single_chart_with_annotations()
    names = [layer.get("name") for layer in specs["layer"]]
    assert names == [
        "annotation_band_0",
        "annotation_rule_0",
        "annotation_rule_hit_0",
        "annotation_marker_0",
        None,  # the chart itself
        "annotation_text_0",
    ]
    assert specs["layer"][0]["data"] == {"name": "d_annotations"}
    # The instant-annotation hover tolerance is one event of the chart (15 minutes)
    assert "<= 900000" in json.dumps(specs["layer"][1]["encoding"]["opacity"])


def test_hovered_and_pinned_annotations_take_the_highlight_colour():
    """A pinned annotation takes the secondary colour and a hovered one its hover shade, while others keep their own colour."""
    specs = _single_chart_with_annotations()
    for layer in [specs["layer"][i] for i in (0, 1, 3)]:  # band, rule and marker
        color = layer["encoding"]["color"]
        pinned, hovered, alert = color["condition"]
        assert "annotation_pin_time_0" in pinned["test"]
        assert pinned["value"] == "var(--secondary-color)"
        assert "annotation_hover_time_0" in hovered["test"]
        assert hovered["value"] == "var(--secondary-hover-color)"
        assert alert["test"] == "datum.type == 'alert'"
        assert color["value"] == "var(--gray)"
    text = specs["layer"][5]
    assert text["encoding"]["color"] == {
        "value": "#333"
    }, "annotation text stays legible on white"


def test_shift_click_keeps_earlier_pinned_annotations():
    """Shift-click pins another annotation, keeping the earlier pins, as in the fast chart."""
    specs = _single_chart_with_annotations()
    band = specs["layer"][0]
    pin = next(p for p in band["params"] if p["name"] == "annotation_pin_time_0")
    assert "toggle" not in pin["select"], "Vega-Lite's default toggle is shift-click"
    # Every pinned time is tested, not only the first
    pinned_test = band["encoding"]["color"]["condition"][0]["test"]
    assert "annotation_pin_time_0['event_start'][1]" in pinned_test
    hovered_test = band["encoding"]["color"]["condition"][1]["test"]
    assert "annotation_hover_time_0['event_start'][1]" not in hovered_test


def test_instant_annotations_can_be_hovered_on_an_instantaneous_sensor():
    """An instantaneous sensor's chart still gives instant annotations a hover tolerance (one hour, as in the fast chart)."""
    specs = _single_chart_with_annotations(step=0)
    rule_opacity = json.dumps(specs["layer"][1]["encoding"]["opacity"])
    assert "<= 0)" not in rule_opacity and "<= 0 " not in rule_opacity
    assert "<= 3600000" in rule_opacity
