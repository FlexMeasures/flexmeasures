import re
import click


def validate_color_hex(ctx, param, value):
    """
    Validates that a given value is a valid hex color code.

    Parameters:
    :param ctx:     Click context.
    :param param:   Click parameter. Hex value.
    """
    if isinstance(param, str):
        param_name = param
    else:
        param_name = param.name

    if value is None:
        return value

    hex_pattern = re.compile(r"^#?([A-Fa-f0-9]{6}|[A-Fa-f0-9]{6})$")
    if re.match(hex_pattern, value):
        return value
    else:
        raise click.BadParameter(f"{param_name} must be a valid/full hex color code.")


def validate_url(ctx, param, value):
    """
    Validates that a given value is a valid URL format using regex.

    Parameters:
    :param ctx:     Click context.
    :param param:   Click parameter. URL value.
    :param value:   The URL to validate.
    """
    if value is None:
        return value

    url_regex = re.compile(
        r"^(https?|ftp)://"  # Protocol: http, https, or ftp
        r"((([A-Za-z0-9-]+\.)+[A-Za-z]{2,6})|"  # Domain name
        r"(\d{1,3}\.){3}\d{1,3})"  # OR IPv4
        r"(:\d+)?"  # Port
        r"(/([A-Za-z0-9$_.+!*\'(),;?&=-]|%[0-9A-Fa-f]{2})*)*"  # Path
        r"(\?([A-Za-z0-9$_.+!*\'(),;?&=-]|%[0-9A-Fa-f]{2})*)?"  # Query string
    )

    if not url_regex.match(value):
        raise click.BadParameter(f"'{value}' is not a valid URL.")

    # check if more than 255 characters
    if len(value) > 255:
        raise click.BadParameter(
            "provided logo-url is too long. Maximum length is 255 characters."
        )

    return value
