from flexmeasures.ui.utils.color_defaults import darken_color, lighten_color, rgba_color


def test_color_utils() -> None:
    primary_color: str = "#1a3443"
    secondary_color: str = "f1a122"

    assert darken_color(primary_color, 7) == "#18303e"
    assert darken_color(primary_color, 4) == "#183140"
    assert rgba_color(primary_color, 0.2) == "rgba(26, 52, 67, 0.2)"
    assert lighten_color(secondary_color, 4) == "#f1a42a"
    assert rgba_color(secondary_color, 0.2) == "rgba(241, 161, 34, 0.2)"
