import pytest

from flexmeasures.data.models.charts.defaults import merge_vega_lite_specs


@pytest.mark.parametrize(
    "default_specs, custom_specs, expected_specs",
    [
        (
            {"legend": {"titleFontSize": 16}},
            {"title": "foo"},
            {"legend": {"titleFontSize": 16}, "title": "foo"},
        ),
        (
            {"title": {"fontSize": 16}},
            {"title": "foo"},
            {"title": {"fontSize": 16, "text": "foo"}},
        ),
    ],
)
def test_merge_vega_lite_specs(
    default_specs: dict, custom_specs: dict, expected_specs: dict
):
    assert merge_vega_lite_specs(default_specs, custom_specs) == expected_specs
