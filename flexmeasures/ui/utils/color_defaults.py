from __future__ import annotations
from flexmeasures.data.models.user import Account


def get_color_settings(account: Account | None) -> dict:
    """
    This function returns the primary and secondary color settings for the UI.

    It also provides variations of the primary and secondary colors, such as border color, hover color, and transparent color.
    """

    primary_color: str = "#1a3443"
    secondary_color: str = "#f1a122"
    if account:
        primary_color = str(
            account.primary_color
            or (
                account.consultancy_account
                and account.consultancy_account.primary_color
            )
            or primary_color
        )
        secondary_color = str(
            account.secondary_color
            or (
                account.consultancy_account
                and account.consultancy_account.secondary_color
            )
            or secondary_color
        )

    # Compute variations
    primary_border_color = darken_color(primary_color, 7)
    primary_hover_color = darken_color(primary_color, 4)
    primary_transparent = rgba_color(primary_color, 0.2)
    secondary_hover_color = lighten_color(secondary_color, 4)
    secondary_transparent = rgba_color(secondary_color, 0.2)

    return {
        "primary_color": primary_color,
        "primary_border_color": primary_border_color,
        "primary_hover_color": primary_hover_color,
        "primary_transparent": primary_transparent,
        "secondary_color": secondary_color,
        "secondary_hover_color": secondary_hover_color,
        "secondary_transparent": secondary_transparent,
    }


def darken_color(hex_color: str, percentage: int) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r = int(r * (1 - percentage / 100))
    g = int(g * (1 - percentage / 100))
    b = int(b * (1 - percentage / 100))
    return f"#{r:02x}{g:02x}{b:02x}"


def lighten_color(hex_color: str, percentage: int) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r = int(r + (255 - r) * percentage / 100)
    g = int(g + (255 - g) * percentage / 100)
    b = int(b + (255 - b) * percentage / 100)
    return f"#{r:02x}{g:02x}{b:02x}"


def rgba_color(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"
