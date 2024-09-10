import re
import click


def validate_color_hex(ctx, param, value):
    """
    Optional parameter validation

    Validates that a given value is a valid hex color code.

    Parameters:
    :param ctx:     Click context.
    :param param:   Click parameter. Hex value.
    """
    if value is None:
        return value

    hex_pattern = re.compile(r"^#?([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")

    if re.match(hex_pattern, value):
        return value
    else:
        error_message: str = f"{value} is not a valid hex color code."
        if ctx is None:  # Non-CLI context
            raise ValueError(error_message)
        else:  # CLI context
            raise click.BadParameter(error_message)


def validate_url(ctx, param, value):
    """
    Optional parameter valdiation

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
        error_message: str = f"'{value}' is not a valid URL."
        if ctx is None:  # Non-CLI context
            raise ValueError(error_message)
        else:  # CLI context
            raise click.BadParameter(error_message)

    # check if more than 255 characters
    if len(value) > 255:
        error_message: str = (
            "provided logo-url is too long. Maximum length is 255 characters."
        )
        if ctx is None:  # Non-CLI context
            raise ValueError(error_message)
        else:  # CLI context
            raise click.BadParameter(error_message)

    return value
