import logging
from typing import Optional, Union
from urllib.parse import urlparse

import re
from tldextract import extract as tld_extract
from tldextract.tldextract import ExtractResult as TldExtractResult
from flask import request, current_app, has_request_context

from flexmeasures.utils.time_utils import get_first_day_of_next_month


"""
Functionality to support parsing and building USEF's EA1 addressing scheme [1],
which is mostly taken from IETF RFC 3720 [2]:

This is the complete structure of an EA1 address:

ea1.{date code}.{reversed domain name}:{locally unique string}

for example "ea1.2021-01.io.flexmeasures.company:sensor14"

- "ea1" is a constant, indicating this is a type 1 USEF entity address
- The date code "must be a date during which the naming authority owned
    the domain name used in this format, and should be the first month in which the domain name was
    owned by this naming authority at 00:01 GMT of the first day of the month.
- The reversed domain name is taken from the naming authority
    (person or organization) creating this entity address
- The locally unique string can be used for local purposes, and FlexMeasures
  uses it to identify the resource (more information in parse_entity_address).
  Fields in the locally unique string are separated by colons, see for other examples
  IETF RFC 3721, page 6 [3].
  ([2] says it's possible to use dashes, dots or colons ― dashes and dots might come up in
  latitude/longitude coordinates of sensors)

TODO: This needs to be in the FlexMeasures documentation.

[1] https://www.usef.energy/app/uploads/2020/01/USEF-Flex-Trading-Protocol-Specifications-1.01.pdf
[2] https://tools.ietf.org/html/rfc3720
[3] https://tools.ietf.org/html/rfc3721
"""


ADDR_SCHEME = "ea1"


class EntityAddressException(Exception):
    pass


def build_entity_address(
    entity_info: dict, entity_type: str, host: Optional[str] = None
) -> str:
    """
    Build an entity address.

    If the host is not given, it is attempted to be taken from the request.
    entity_info is expected to contain the required fields for the custom string.

    Returns the address as string.
    """
    if host is None:
        if has_request_context():
            host = urlparse(request.url).netloc
        else:
            # Assume localhost (for CLI/tests/simulations)
            host = "localhost"

    def build_field(field: str, required: bool = True):
        if required and field not in entity_info:
            raise EntityAddressException(
                f"Cannot find required field '{field}' to build entity address."
            )
        if field not in entity_info:
            return ""
        return f":{entity_info[field]}"

    if entity_type == "connection":
        locally_unique_str = (
            f"{build_field('owner_id', required=False)}{build_field('asset_id')}"
        )
    elif entity_type == "sensor":
        locally_unique_str = f"{build_field('weather_sensor_type_name')}{build_field('latitude')}{build_field('longitude')}"
    elif entity_type == "market":
        locally_unique_str = f"{build_field('market_name')}"
    elif entity_type == "event":
        locally_unique_str = f"{build_field('owner_id', required=False)}{build_field('asset_id')}{build_field('event_id')}{build_field('event_type')}"
    else:
        raise EntityAddressException(f"Unrecognized entity type: {entity_type}")
    return build_ea_scheme_and_naming_authority(host) + locally_unique_str


def parse_entity_address(entity_address: str, entity_type: str) -> dict:
    """
    Parses a generic asset name into an info dict.

    The entity_address must be a valid type 1 USEF entity address.
    That is, it must follow the EA1 addressing scheme recommended by USEF.
    In addition, FlexMeasures expects the identifying string to contain information in
    a certain structure.

    For example:

        connection = ea1.2018-06.localhost:40:30
        connection = ea1.2018-06.io.flexmeasures:<owner_id>:<asset_id>
        sensor = ea1.2018-06.io.flexmeasures:temperature:52:73.0
        sensor = ea1.2018-06.io.flexmeasures:<sensor_type>:<latitude>:<longitude>
        market = ea1.2018-06.io.flexmeasures:epex_da
        market = ea1.2018-06.io.flexmeasures:<market_name>
        event = ea1.2018-06.io.flexmeasures:40:30:302:soc
        event = ea1.2018-06.io.flexmeasures:<owner_id>:<asset_id>:<event_id>:<event_type>

    Returns a dictionary with scheme, naming_authority and various other fields,
    depending on the entity type (see examples above).
    Returns None if entity type is unknown or entity_address is not parseable.
    We recommend to `return invalid_domain()` in that case.
    """
    # we can rigidly test the start
    if not entity_address.startswith(ADDR_SCHEME):
        raise EntityAddressException(
            f"A valid type 1 USEF entity address starts with '{ADDR_SCHEME}', please review {entity_address}"
        )
    date_regex = r"[0-9]{4}-[0-9]{2}"
    if not re.search(fr"^{date_regex}$", entity_address[4:11]):
        raise EntityAddressException(
            f"After '{ADDR_SCHEME}.', a date spec of the format {date_regex} is expected."
        )
    # Also the entity type
    if entity_type not in ("connection", "sensor", "market", "event"):
        raise EntityAddressException(f"Unrecognized entity type: {entity_type}")

    if entity_type == "connection":
        match = re.search(
            r"^"
            r"(?P<scheme>.+)\."
            fr"(?P<naming_authority>{date_regex}\.[^:]+)"  # everything until the colon (no port)
            r":"
            r"((?P<owner_id>\d+):)*"  # owner id is optional
            r"(?P<asset_id>\d+)"
            r"$",
            entity_address,
        )
        if match:
            value_types = {
                "scheme": str,
                "naming_authority": str,
                "owner_id": int,
                "asset_id": int,
            }
            return _typed_regex_results(match, value_types)
    elif entity_type == "sensor":
        match = re.search(
            r"^"
            r"(?P<scheme>.+)"
            r"\."
            fr"(?P<naming_authority>{date_regex}\.[^:]+)"
            r":"
            r"(?=[a-zA-Z])(?P<weather_sensor_type_name>[\w]+)"  # should start with at least one letter
            r":"
            r"(?P<latitude>\-?\d+(\.\d+)?)"
            r":"
            r"(?P<longitude>\-?\d+(\.\d+)?)"
            r"$",
            entity_address,
        )
        if match:
            value_types = {
                "scheme": str,
                "naming_authority": str,
                "weather_sensor_type_name": str,
                "latitude": float,
                "longitude": float,
            }
            return _typed_regex_results(match, value_types)
    elif entity_type == "market":
        match = re.search(
            r"^"
            r"(?P<scheme>.+)"
            r"\."
            fr"(?P<naming_authority>{date_regex}\.[^:]+)"
            r":"
            r"(?=[a-zA-Z])(?P<market_name>[\w]+)"  # should start with at least one letter
            r"$",
            entity_address,
        )
        if match:
            value_types = {"scheme": str, "naming_authority": str, "market_name": str}
            return _typed_regex_results(match, value_types)
    elif entity_type == "event":
        match = re.search(
            r"^"
            r"(?P<scheme>.+)"
            r"\."
            fr"(?P<naming_authority>{date_regex}\.[^:]+)"
            r":"
            r"((?P<owner_id>\d+):)*"  # owner id is optional
            r"(?P<asset_id>\d+)"
            r":"
            r"(?P<event_id>\d+)"
            r":"
            r"(?P<event_type>.+)"
            r"$",
            entity_address,
        )
        if match:
            value_types = {
                "scheme": str,
                "naming_authority": str,
                "owner_id": int,
                "asset_id": int,
                "event_id": int,
                "event_type": str,
            }
            return _typed_regex_results(match, value_types)

    # Finally, we simply raise without precise information what went wrong
    raise EntityAddressException(f"Could not parse {entity_address}.")


def build_ea_scheme_and_naming_authority(
    host: str, host_auth_start_month: Optional[str] = None
) -> str:
    """
    This function creates the host identification part of
    USEF's EA1 addressing scheme, so everything but the locally unique string.

    If not given nor configured, host_auth_start_month is the start of the next month for
    localhost.
    """
    domain_parts: TldExtractResult = get_domain_parts(host)

    if host_auth_start_month is None:
        config_var_domain_key = ".".join(
            filter(
                lambda x: x,
                [domain_parts.subdomain, domain_parts.domain, domain_parts.suffix],
            )
        )
        if config_var_domain_key in current_app.config.get(
            "FLEXMEASURES_HOSTS_AND_AUTH_START", {}
        ):
            host_auth_start_month = current_app.config.get(
                "FLEXMEASURES_HOSTS_AND_AUTH_START", {}
            )[config_var_domain_key]
        elif domain_parts.domain in ("localhost", "127.0.0.1"):
            host_auth_start_month = get_first_day_of_next_month().strftime("%Y-%m")
        else:
            raise Exception(
                f"Could not find out when authority for {config_var_domain_key} started. Is FLEXMEASURES_HOSTS_AND_AUTH_START configured for it?"
            )
    regex = r"^\d{4}-\d{2}$"
    if not re.search(regex, host_auth_start_month):
        raise ValueError(
            f"{host_auth_start_month} should adhere to the format {regex}."
        )
    if not int(host_auth_start_month[-2:]) in range(1, 13):
        raise ValueError(
            f"Month in {host_auth_start_month} should be in the range of 1 to 12."
        )

    reversed_domain_name = reverse_domain_name(domain_parts)
    if reversed_domain_name == "":
        raise Exception(f"Could not make domain name from {host}!")
    return f"{ADDR_SCHEME}.{host_auth_start_month}.{reversed_domain_name}"


def reverse_domain_name(domain: Union[str, TldExtractResult]) -> str:
    """
    Returns the reverse notation of the domain.
    You can pass in a string domain or an extraction result from tldextract
    """
    if isinstance(domain, str):
        domain_parts: TldExtractResult = get_domain_parts(domain)
    else:
        domain_parts = domain

    suffix = domain_parts.suffix
    if suffix != "":
        if "." in suffix:
            suffix = ".".join(suffix.split(".")[::-1])
        suffix = f"{suffix}."

    domain = domain_parts.domain

    reversed_subdomain = ""
    if domain_parts.subdomain != "":
        sd_list = ".".join(domain_parts.subdomain.split(".")[::-1])
        reversed_subdomain = f".{sd_list}"

    return f"{suffix}{domain}{reversed_subdomain}"


def get_domain_parts(domain: str) -> TldExtractResult:
    """wrapper for calling tldextract as it logs things about file locks we don't care about."""
    logger = logging.getLogger()
    level = logger.getEffectiveLevel()
    logger.setLevel(logging.ERROR)
    domain_parts: TldExtractResult = tld_extract(domain)
    logging.getLogger().setLevel(level)
    return domain_parts


def _typed_regex_results(match, value_types) -> dict:
    return {
        k: v_type(v) if v is not None else v
        for k, v, v_type in _zip_dic(match.groupdict(), value_types)
    }


def _zip_dic(*dicts):
    for i in set(dicts[0]).intersection(*dicts[1:]):
        yield (i,) + tuple(d[i] for d in dicts)
