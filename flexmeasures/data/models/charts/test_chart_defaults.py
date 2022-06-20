import altair as alt

from flexmeasures.data.models.charts.defaults import FIELD_DEFINITIONS


def test_default_encodings():
    """Check default encodings for valid vega-lite specifications."""
    for field_name, field_definition in FIELD_DEFINITIONS.items():
        assert alt.PositionFieldDef(**field_definition)
