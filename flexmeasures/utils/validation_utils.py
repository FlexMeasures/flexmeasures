import re


def validate_color_hex(value):
    """
    Validates that a given value is a valid hex color code.

    Parameters:
    :value: The color code to validate.
    """
    if value is None:
        return value

    if value and not value.startswith("#"):
        value = f"#{value}"

    hex_pattern = re.compile(r"^#?([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")

    if re.match(hex_pattern, value):
        return value
    else:
        raise ValueError(f"{value} is not a valid hex color code.")


def validate_url(value):
    """
    Validates that a given value is a valid URL format using regex.

    Parameters:
    :value: The URL to validate.
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
        raise ValueError(f"'{value}' is not a valid URL.")

    # check if more than 255 characters
    if len(value) > 255:
        raise ValueError(
            "provided logo-url is too long. Maximum length is 255 characters."
        )

    return value
